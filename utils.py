from typing import Optional, List, Dict, Any
import re
from datetime import datetime, date
import orgparse


def find_heading_in_content(
    content: str, target_heading: str, level: int
) -> Optional[tuple]:
    lines = content.split("\n")
    heading_pattern = r"^(\*+)\s+(.+)$"

    target_stars = "*" * level

    for i, line in enumerate(lines):
        match = re.match(heading_pattern, line)
        if match:
            stars = match.group(1)
            heading_text = match.group(2).strip()

            if stars == target_stars and heading_text == target_heading:
                end_line = len(lines)

                for j in range(i + 1, len(lines)):
                    next_match = re.match(heading_pattern, lines[j])
                    if next_match:
                        next_stars = next_match.group(1)
                        if len(next_stars) <= len(stars):
                            end_line = j
                            break

                return (i, end_line)

    return None


def extract_title_from_content(content):
    lines = content.split("\n")
    for line in lines:
        if line.startswith("#+title:") or line.startswith("#+TITLE:"):
            return line.split(":", 1)[1].strip()
    return None


def get_heading_content(content: str, heading: str, level: int) -> str:
    heading_pos = find_heading_in_content(content, heading, level)

    if not heading_pos:
        return ""

    start_line, end_line = heading_pos
    lines = content.split("\n")

    if end_line > start_line + 1:
        content_lines = lines[start_line + 1 : end_line]
        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        return "\n".join(content_lines)

    return ""


def update_heading_in_content(
    content: str, old_heading: str, new_heading: str, new_content: str, level: int
) -> str:
    lines = content.split("\n")
    heading_pos = find_heading_in_content(content, old_heading, level)

    if not heading_pos:
        return content

    start_line, end_line = heading_pos

    stars = "*" * level
    new_heading_line = f"{stars} {new_heading}"

    new_lines = lines[:start_line]
    new_lines.append(new_heading_line)

    if new_content.strip():
        new_lines.append("")
        for line in new_content.split("\n"):
            new_lines.append(line)

    new_lines.extend(lines[end_line:])

    return "\n".join(new_lines)


def backup_file(file_path: str) -> str:
    from datetime import datetime

    backup_path = f"{file_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    with open(file_path, "r", encoding="utf-8") as original:
        content = original.read()

    with open(backup_path, "w", encoding="utf-8") as backup:
        backup.write(content)

    return backup_path


def inject_edit_buttons(html_content, file_name):
    heading_pattern = r"(<h([1-6])[^>]*>)(.*?)(</h[1-6]>)"

    def replace_heading(match):
        opening_tag = match.group(1)
        level = match.group(2)
        heading_text = match.group(3)
        closing_tag = match.group(4)

        import urllib.parse

        safe_heading = urllib.parse.quote(heading_text.strip())

        edit_link = f"""
        <a href="/edit/{file_name}?heading={safe_heading}&level={level}" class="edit-btn">
             Edit
        </a>
        """

        add_link = f"""
        <a href="/add/{file_name}?parent_heading={safe_heading}&parent_level={level}" class="add-btn">
             Add Sub
        </a>
        """

        return f"{opening_tag}{heading_text} {edit_link} {add_link}{closing_tag}"

    return re.sub(heading_pattern, replace_heading, html_content)


def parse_org_agenda_items(
    directory: str = "~/denote",
) -> Dict[str, List[Dict[str, Any]]]:
    from pathlib import Path

    path = Path(directory).expanduser()
    org_files = list(path.glob("*.org"))

    agenda_items = {
        "schedules_today": [],
        "deadlines_today": [],
        "todos": {"ACTIVE": [], "NEXT": [], "TODO": [], "WAIT": []},
    }

    today = date.today()

    for file_path in org_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            root = orgparse.load(str(file_path))

            file_title = extract_title_from_content(content)
            is_task_file = "__task" in file_path.name or "_task" in file_path.name

            if not file_title:
                file_title = file_path.stem

            processed_items = set()

            def parse_timestamps_in_content(heading_text, content_after_heading):
                scheduled = None
                deadline = None

                scheduled_match = re.search(
                    r"SCHEDULED:\s*<([^>]+)>", content_after_heading
                )
                if scheduled_match:
                    try:
                        date_str = scheduled_match.group(1)
                        date_part = date_str.split()[0]
                        scheduled = datetime.strptime(date_part, "%Y-%m-%d").date()
                    except:
                        pass

                deadline_match = re.search(
                    r"DEADLINE:\s*<([^>]+)>", content_after_heading
                )
                if deadline_match:
                    try:
                        date_str = deadline_match.group(1)
                        date_part = date_str.split()[0]
                        deadline = datetime.strptime(date_part, "%Y-%m-%d").date()
                    except:
                        pass

                return scheduled, deadline

            content_sections = {}
            lines = content.split("\n")
            current_heading = None
            current_content = []

            for line in lines:
                heading_match = re.match(r"^(\*+)\s+(.+)", line)
                if heading_match:
                    if current_heading:
                        content_sections[current_heading] = "\n".join(current_content)

                    current_heading = heading_match.group(2).strip()
                    current_content = []
                else:
                    current_content.append(line)

            if current_heading:
                content_sections[current_heading] = "\n".join(current_content)

            def walk_nodes(node):
                if hasattr(node, "heading") and node.heading:
                    todo_keyword = getattr(node, "todo", None)
                    original_heading = node.heading

                    if not todo_keyword and node.heading:
                        todo_match = re.match(
                            r"^(ACTIVE|NEXT|TODO|WAIT|DONE)\s+", node.heading
                        )
                        if todo_match:
                            todo_keyword = todo_match.group(1)
                            original_heading = node.heading[
                                len(todo_match.group(0)) :
                            ].strip()

                    heading_content = content_sections.get(
                        original_heading, content_sections.get(node.heading, "")
                    )
                    scheduled, deadline = parse_timestamps_in_content(
                        original_heading, heading_content
                    )

                    item_data = {
                        "title": original_heading,
                        "file_name": file_path.name,
                        "file_title": file_title,
                        "todo_keyword": todo_keyword,
                        "tags": getattr(node, "tags", []),
                        "priority": getattr(node, "priority", None),
                        "scheduled": scheduled,
                        "deadline": deadline,
                        "is_task_file": is_task_file,
                    }

                    if scheduled and scheduled == today:
                        item_id = f"schedule:{file_path.name}:{original_heading}"
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["schedules_today"].append(item_data.copy())

                    if deadline and deadline == today:
                        item_id = f"deadline:{file_path.name}:{original_heading}"
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["deadlines_today"].append(item_data.copy())

                    if todo_keyword and todo_keyword in [
                        "ACTIVE",
                        "NEXT",
                        "TODO",
                        "WAIT",
                    ]:
                        item_id = (
                            f"todo:{file_path.name}:{todo_keyword}:{original_heading}"
                        )
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["todos"][todo_keyword].append(item_data.copy())

                if hasattr(node, "children"):
                    for child in node.children:
                        walk_nodes(child)

            if hasattr(root, "children"):
                for child in root.children:
                    walk_nodes(child)

        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            continue

    return agenda_items


def format_agenda_date(date_obj):
    if isinstance(date_obj, date):
        return date_obj.strftime("%Y-%m-%d")
    return str(date_obj)


def parse_org_agenda_items_task_only(
    directory: str = "~/denote",
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Parse org agenda items but only include TODOs from files with 'task' filetag.
    Denote filetags are indicated by double underscores in the filename.
    """
    from pathlib import Path

    path = Path(directory).expanduser()
    org_files = list(path.glob("*.org"))

    agenda_items = {
        "schedules_today": [],
        "deadlines_today": [],
        "todos": {"ACTIVE": [], "NEXT": [], "TODO": [], "WAIT": []},
    }

    today = date.today()


    def has_task_filetag(filename: str) -> bool:
        """Check if filename contains 'task' as a denote filetag (indicated by __)"""
        # Denote filetags are separated by double underscores
        parts = filename.split("__")
        # Check if 'task' appears in any filetag
        for part in parts[1:]:  # Skip the first part (ID and title)
            # Remove .org extension from last part
            clean_part = part.replace(".org", "").lower()
            # Split by underscores to handle compound tags like 'blackberry_task'
            tag_components = clean_part.split("_")
            if "task" in tag_components:
                return True
        return False

    for file_path in org_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Check if this file has the 'task' filetag
            is_task_file = has_task_filetag(file_path.name)

            root = orgparse.load(str(file_path))
            file_title = extract_title_from_content(content)

            if not file_title:
                file_title = file_path.stem

            processed_items = set()

            def parse_timestamps_in_content(heading_text, content_after_heading):
                scheduled = None
                deadline = None

                scheduled_match = re.search(
                    r"SCHEDULED:\s*<([^>]+)>", content_after_heading
                )
                if scheduled_match:
                    try:
                        date_str = scheduled_match.group(1)
                        date_part = date_str.split()[0]
                        scheduled = datetime.strptime(date_part, "%Y-%m-%d").date()
                    except:
                        pass

                deadline_match = re.search(
                    r"DEADLINE:\s*<([^>]+)>", content_after_heading
                )
                if deadline_match:
                    try:
                        date_str = deadline_match.group(1)
                        date_part = date_str.split()[0]
                        deadline = datetime.strptime(date_part, "%Y-%m-%d").date()
                    except:
                        pass

                return scheduled, deadline

            content_sections = {}
            lines = content.split("\n")
            current_heading = None
            current_content = []

            for line in lines:
                heading_match = re.match(r"^(\*+)\s+(.+)", line)
                if heading_match:
                    if current_heading:
                        content_sections[current_heading] = "\n".join(current_content)

                    current_heading = heading_match.group(2).strip()
                    current_content = []
                else:
                    current_content.append(line)

            if current_heading:
                content_sections[current_heading] = "\n".join(current_content)

            def walk_nodes(node):
                if hasattr(node, "heading") and node.heading:
                    todo_keyword = getattr(node, "todo", None)
                    original_heading = node.heading

                    if not todo_keyword and node.heading:
                        todo_match = re.match(
                            r"^(ACTIVE|NEXT|TODO|WAIT|DONE)\s+", node.heading
                        )
                        if todo_match:
                            todo_keyword = todo_match.group(1)
                            original_heading = node.heading[
                                len(todo_match.group(0)) :
                            ].strip()

                    heading_content = content_sections.get(
                        original_heading, content_sections.get(node.heading, "")
                    )
                    scheduled, deadline = parse_timestamps_in_content(
                        original_heading, heading_content
                    )

                    item_data = {
                        "title": original_heading,
                        "file_name": file_path.name,
                        "file_title": file_title,
                        "todo_keyword": todo_keyword,
                        "tags": getattr(node, "tags", []),
                        "priority": getattr(node, "priority", None),
                        "scheduled": scheduled,
                        "deadline": deadline,
                        "is_task_file": is_task_file,
                    }

                    # Always include scheduled and deadline items regardless of filetag
                    if scheduled and scheduled == today:
                        item_id = f"schedule:{file_path.name}:{original_heading}"
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["schedules_today"].append(item_data.copy())

                    if deadline and deadline == today:
                        item_id = f"deadline:{file_path.name}:{original_heading}"
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["deadlines_today"].append(item_data.copy())

                    # Only include TODO items if the file has 'task' filetag
                    if (
                        todo_keyword
                        and todo_keyword in ["ACTIVE", "NEXT", "TODO", "WAIT"]
                        and is_task_file
                    ):
                        item_id = (
                            f"todo:{file_path.name}:{todo_keyword}:{original_heading}"
                        )
                        if item_id not in processed_items:
                            processed_items.add(item_id)
                            agenda_items["todos"][todo_keyword].append(item_data.copy())

                if hasattr(node, "children"):
                    for child in node.children:
                        walk_nodes(child)

            if hasattr(root, "children"):
                for child in root.children:
                    walk_nodes(child)

        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            continue

    return agenda_items
