import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import asyncio
from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from orgpython import to_html

from utils import (
    extract_title_from_content,
    find_heading_in_content,
    get_heading_content,
    inject_edit_buttons,
    parse_org_agenda_items,
    update_heading_in_content,
)
import xmpp_bot
import uvicorn

load_dotenv()
AUTH = os.getenv("AUTH")
app = FastAPI(title="Orgmode Web")
security = HTTPBearer(auto_error=False)


async def git_pull():
    denote_path = Path("~/denote").expanduser()
    try:
        result = subprocess.run(
            ["git", "pull"], cwd=denote_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"Git pull successful: {result.stdout}")
        else:
            print(f"Git pull failed: {result.stderr}")
    except Exception as e:
        print(f"Error during git pull: {e}")


async def git_commit_and_push():
    denote_path = Path("~/denote").expanduser()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        subprocess.run(["git", "add", "."], cwd=denote_path, check=True)

        commit_message = f"sync org-web {timestamp}"
        subprocess.run(
            ["git", "commit", "-m", commit_message], cwd=denote_path, check=True
        )

        subprocess.run(["git", "push"], cwd=denote_path, check=True)

        print(f"Git commit and push successful: {commit_message}")

    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
    except Exception as e:
        print(f"Error during git operations: {e}")


async def periodic_git_pull():
    while True:
        await git_pull()
        await asyncio.sleep(300)


async def run_uvicorn():
    config = uvicorn.Config("main:app", host="0.0.0.0", port=8090, reload=False)
    server = uvicorn.Server(config)
    await server.serve()


async def run_xmpp():
    await xmpp_bot.main_async()


async def main():
    await asyncio.gather(
        run_uvicorn(),
        run_xmpp(),
        periodic_git_pull(),
    )


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


async def verify_token(request: Request, token: Optional[str] = Cookie(None)):
    if token == AUTH:
        return True
    return RedirectResponse(url="/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(
        "login.html", {"request": request, "title": "Login"}
    )


@app.post("/login")
async def login(token: str = Form(...)):
    if token == AUTH:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="token", value=token, httponly=True, max_age=86400)
        return response
    else:
        return HTMLResponse("Invalid token", status_code=401)


def load_all_org_files(directory: str = "~/denote"):
    path = Path(directory).expanduser()
    org_files = list(path.glob("*.org"))
    result = []

    for file in org_files:
        try:
            with open(file, "r", encoding="utf-8") as target:
                content = target.read()

            title = extract_title_from_content(content)
            if not title:
                title = file.stem

            html_content = to_html(content, toc=True, offset=0, highlight=True)

            result.append(
                {
                    "file_path": str(file),
                    "file_name": file.name,
                    "title": title,
                    "html_content": html_content,
                    "raw_content": content,
                }
            )
        except Exception as e:
            print(f"Error loading {file}: {e}")

    return result


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, auth=Depends(verify_token)):
    if isinstance(auth, RedirectResponse):
        return auth
    org_files = load_all_org_files()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "title": "Orgmode Web", "org_files": org_files},
    )


@app.get("/org/{file_name}", response_class=HTMLResponse)
async def view_org_file(request: Request, file_name: str, auth=Depends(verify_token)):
    if isinstance(auth, RedirectResponse):
        return auth

    org_files = load_all_org_files()
    target_file = None
    for file in org_files:
        if file["file_name"] == file_name:
            target_file = file
            break

    if not target_file:
        return HTMLResponse("File not found", status_code=404)

    html_with_buttons = inject_edit_buttons(target_file["html_content"], file_name)

    return templates.TemplateResponse(
        "org_view.html",
        {
            "request": request,
            "title": target_file["title"],
            "html_content": html_with_buttons,
            "file_name": file_name,
        },
    )


@app.get("/edit/{file_name}", response_class=HTMLResponse)
async def edit_form(
    request: Request,
    file_name: str,
    heading: str = "",
    level: str = "1",
    auth=Depends(verify_token),
):
    if isinstance(auth, RedirectResponse):
        return auth
    import urllib.parse

    decoded_heading = urllib.parse.unquote(heading)

    denote_path = Path("~/denote").expanduser()
    file_path = denote_path / file_name

    existing_content = ""
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            existing_content = get_heading_content(content, decoded_heading, int(level))
        except Exception as e:
            print(f"Error reading existing content: {e}")

    return templates.TemplateResponse(
        "edit_form.html",
        {
            "request": request,
            "file_name": file_name,
            "heading": decoded_heading,
            "level": level,
            "existing_content": existing_content,
            "title": f"Edit: {decoded_heading}",
        },
    )


def add_heading_to_content(
    content: str,
    parent_heading: str,
    parent_level: int,
    new_heading: str,
    new_content: str,
    new_level: int,
    auth=Depends(verify_token),
) -> str:

    if isinstance(auth, RedirectResponse):
        return auth
    lines = content.split("\n")

    if parent_heading:
        heading_pos = find_heading_in_content(content, parent_heading, parent_level)
        if not heading_pos:
            return content

        start_line, end_line = heading_pos
        insert_position = end_line
    else:
        insert_position = len(lines)

    stars = "*" * new_level
    new_heading_line = f"{stars} {new_heading}"

    new_lines = lines[:insert_position]

    if new_lines and new_lines[-1].strip():
        new_lines.append("")

    new_lines.append(new_heading_line)

    if new_content.strip():
        new_lines.append("")
        for line in new_content.split("\n"):
            new_lines.append(line)

    new_lines.extend(lines[insert_position:])

    return "\n".join(new_lines)


@app.post("/edit-heading")
async def edit_heading(
    file_name: str = Form(...),
    heading_level: str = Form(...),
    old_heading: str = Form(...),
    new_heading: str = Form(...),
    new_content: str = Form(""),
    auth=Depends(verify_token),
):

    if isinstance(auth, RedirectResponse):
        return auth
    try:
        denote_path = Path("~/denote").expanduser()
        file_path = denote_path / file_name

        if not file_path.exists():
            return HTMLResponse("File not found", status_code=404)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

            updated_content = update_heading_in_content(
                content, old_heading, new_heading, new_content, int(heading_level)
            )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        print(f"Successfully updated {file_name}")
        print(f"Changed '{old_heading}' to '{new_heading}'")

        await git_commit_and_push()

        return RedirectResponse(url=f"/org/{file_name}", status_code=303)

    except Exception as e:
        print(f"Error updating file: {e}")
        return HTMLResponse(f"Error updating file: {e}", status_code=500)


@app.get("/add/{file_name}", response_class=HTMLResponse)
async def add_form(
    request: Request,
    file_name: str,
    parent_heading: str = "",
    parent_level: str = "1",
    auth=Depends(verify_token),
):
    if isinstance(auth, RedirectResponse):
        return auth
    import urllib.parse

    decoded_parent_heading = (
        urllib.parse.unquote(parent_heading) if parent_heading else ""
    )

    return templates.TemplateResponse(
        "add_form.html",
        {
            "request": request,
            "file_name": file_name,
            "parent_heading": decoded_parent_heading,
            "parent_level": parent_level,
            "title": f"Add new heading to {file_name}",
        },
    )


@app.post("/add-heading")
async def add_heading(
    file_name: str = Form(...),
    parent_heading: str = Form(""),
    parent_level: str = Form("1"),
    new_heading: str = Form(...),
    new_content: str = Form(""),
    new_level: str = Form("1"),
    auth=Depends(verify_token),
):

    if isinstance(auth, RedirectResponse):
        return auth
    try:
        denote_path = Path("~/denote").expanduser()
        file_path = denote_path / file_name

        if not file_path.exists():
            return HTMLResponse("File not found", status_code=404)

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        updated_content = add_heading_to_content(
            content,
            parent_heading if parent_heading else None,
            int(parent_level) if parent_heading else 1,
            new_heading,
            new_content,
            int(new_level),
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

        print(f"Successfully added heading '{new_heading}' to {file_name}")

        await git_commit_and_push()

        return RedirectResponse(url=f"/org/{file_name}", status_code=303)

    except Exception as e:
        print(f"Error adding heading: {e}")
        return HTMLResponse(f"Error adding heading: {e}", status_code=500)


@app.get("/agenda", response_class=HTMLResponse)
async def agenda_view(
    request: Request,
    auth=Depends(verify_token),
):

    if isinstance(auth, RedirectResponse):
        return auth
    try:
        agenda_data = parse_org_agenda_items()

        return templates.TemplateResponse(
            "agenda.html",
            {
                "request": request,
                "title": "Agenda",
                "agenda_data": agenda_data,
                "today": date.today().strftime("%Y-%m-%d"),
            },
        )
    except Exception as e:
        print(f"Error loading agenda: {e}")
        return HTMLResponse(f"Error loading agenda: {e}", status_code=500)



async def async_main():
    await asyncio.gather(
        run_uvicorn(),
        run_xmpp(),
        periodic_git_pull()
    )

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
