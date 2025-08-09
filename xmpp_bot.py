import asyncio
import json
import logging
import os
from datetime import datetime, time
from typing import Any, Dict, Set

from slixmpp import ClientXMPP

from utils import parse_org_agenda_items


class CommandBot(ClientXMPP):

    def __init__(
        self,
        jid,
        password,
        whitelist_file="whitelist.json",
        subscribers_file="subscribers.json",
    ):
        ClientXMPP.__init__(self, jid, password)

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self.message)

        # Command prefix
        self.command_prefix = "/"

        # Files for persistence
        self.whitelist_file = whitelist_file
        self.subscribers_file = subscribers_file

        # Load whitelist and subscribers
        self.whitelist = self.load_whitelist()
        self.subscribers = self.load_subscribers()

        # Notification settings
        self.notification_start = time(8, 0)  # 8:00 AM
        self.notification_end = time(22, 0)  # 10:00 PM
        self.agenda_interval = 2  # hours

        # Tracking for sent notifications
        self.sent_notifications = set()
        self.last_agenda_sent = None

        # Start background tasks
        self.loop = None

    def load_whitelist(self) -> Set[str]:
        """Load whitelist from file"""
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, "r") as f:
                    data = json.load(f)
                    return set(data.get("whitelist", []))
            else:
                # Create default whitelist file
                default_whitelist = set()
                self.save_whitelist(default_whitelist)
                return default_whitelist
        except Exception as e:
            logging.error(f"Error loading whitelist: {e}")
            return set()

    def save_whitelist(self, whitelist: Set[str]):
        """Save whitelist to file"""
        try:
            with open(self.whitelist_file, "w") as f:
                json.dump({"whitelist": list(whitelist)}, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving whitelist: {e}")

    def load_subscribers(self) -> Set[str]:
        """Load subscribers from file"""
        try:
            if os.path.exists(self.subscribers_file):
                with open(self.subscribers_file, "r") as f:
                    data = json.load(f)
                    return set(data.get("subscribers", []))
            else:
                # Create default subscribers file
                default_subscribers = set()
                self.save_subscribers(default_subscribers)
                return default_subscribers
        except Exception as e:
            logging.error(f"Error loading subscribers: {e}")
            return set()

    def save_subscribers(self, subscribers: Set[str]):
        """Save subscribers to file"""
        try:
            with open(self.subscribers_file, "w") as f:
                json.dump({"subscribers": list(subscribers)}, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving subscribers: {e}")

    def is_whitelisted(self, jid: str) -> bool:
        """Check if JID is whitelisted"""
        return str(jid).split("/")[0] in self.whitelist

    def session_start(self, event):
        self.send_presence()
        self.get_roster()

        # Start background notification tasks
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.periodic_agenda_notifications())
        self.loop.create_task(self.schedule_deadline_notifications())

    def message(self, msg):
        if msg["type"] in ("chat", "normal"):
            sender = str(msg["from"]).split("/")[0]
            body = msg["body"].strip()

            # Check whitelist for all interactions
            if not self.is_whitelisted(sender):
                msg.reply(
                    "Access denied. You are not authorized to use this bot."
                ).send()
                return

            if body.startswith(self.command_prefix):
                command = body[1:]
                response = self.handle_command(command, msg)
                msg.reply(response).send()
            else:
                # Normal echo for whitelisted users
                msg.reply("Thanks for sending: %(body)s" % msg).send()

    def handle_command(self, command, msg):
        cmd_parts = command.split()
        if not cmd_parts:
            return "Unknown command"

        cmd_name = cmd_parts[0].lower()
        cmd_args = cmd_parts[1:] if len(cmd_parts) > 1 else []
        sender = str(msg["from"]).split("/")[0]

        if cmd_name == "agenda":
            return self.cmd_agenda(cmd_args)
        elif cmd_name == "help":
            return self.cmd_help(cmd_args)
        elif cmd_name == "time":
            return self.cmd_time(cmd_args)
        elif cmd_name == "ping":
            return self.cmd_ping(cmd_args)
        elif cmd_name == "notifications":
            return self.cmd_notifications(cmd_args)
        elif cmd_name == "subscribe":
            return self.cmd_subscribe(sender)
        elif cmd_name == "unsubscribe":
            return self.cmd_unsubscribe(sender)
        elif cmd_name == "status":
            return self.cmd_status(sender)
        elif cmd_name == "whitelist":
            return self.cmd_whitelist(cmd_args, sender)
        elif cmd_name == "test-notification":
            return self.cmd_test_notification(sender)
        else:
            return f"Unknown command: {cmd_name}\nType /help for available commands"

    def cmd_test_notification(self, sender: str):
        """Schedule a test notification in 1 minute"""
        if sender in self.subscribers:
            # Start the test notification task
            if self.loop:
                self.loop.create_task(self.send_test_notification_delayed())
            return "Test notification scheduled to be sent in 1 minute."
        else:
            return "You must be subscribed to receive test notifications. Use /subscribe first."

    async def send_test_notification_delayed(self):
        """Send a test notification after 1 minute delay"""
        try:
            # Wait 1 minute
            await asyncio.sleep(60)

            # Get current agenda
            agenda = parse_org_agenda_items()
            agenda_text = self.format_agenda(agenda)

            # Send test notification
            await self.send_notification_to_subscribers(
                f"TEST NOTIFICATION\n\n{agenda_text}"
            )

        except Exception as e:
            logging.error(f"Error sending test notification: {e}")

    def cmd_agenda(self, args):
        """Agenda Command"""
        try:
            agenda = parse_org_agenda_items()
            return self.format_agenda(agenda)
        except Exception as e:
            return f"Error loading agenda: {e}"

    def cmd_subscribe(self, sender: str):
        """Subscribe to notifications"""
        if sender not in self.subscribers:
            self.subscribers.add(sender)
            self.save_subscribers(self.subscribers)
            return "Successfully subscribed to notifications."
        else:
            return "You are already subscribed to notifications."

    def cmd_unsubscribe(self, sender: str):
        """Unsubscribe from notifications"""
        if sender in self.subscribers:
            self.subscribers.remove(sender)
            self.save_subscribers(self.subscribers)
            return "Successfully unsubscribed from notifications."
        else:
            return "You are not subscribed to notifications."

    def cmd_status(self, sender: str):
        """Show subscription status"""
        is_subscribed = sender in self.subscribers
        is_whitelisted = sender in self.whitelist
        return f"Status:\n- Whitelisted: {is_whitelisted}\n- Subscribed: {is_subscribed}\n- Notification hours: {self.notification_start.strftime('%H:%M')} - {self.notification_end.strftime('%H:%M')}"

    def cmd_whitelist(self, args, sender: str):
        """Manage whitelist (admin function)"""
        # Simple admin check - you can enhance this
        admin_jids = {sender}  # Add your admin JIDs here

        if sender not in admin_jids:
            return "Access denied. Admin privileges required."

        if not args:
            return f"Whitelisted users: {', '.join(self.whitelist) if self.whitelist else 'None'}"

        action = args[0].lower()
        if len(args) < 2:
            return "Usage: /whitelist [add|remove] <jid>"

        jid = args[1]

        if action == "add":
            self.whitelist.add(jid)
            self.save_whitelist(self.whitelist)
            return f"Added {jid} to whitelist."
        elif action == "remove":
            if jid in self.whitelist:
                self.whitelist.remove(jid)
                self.save_whitelist(self.whitelist)
                return f"Removed {jid} from whitelist."
            else:
                return f"{jid} is not in whitelist."
        else:
            return "Usage: /whitelist [add|remove] <jid>"

    def cmd_notifications(self, args):
        """Notification settings command"""
        if len(args) >= 2:
            try:
                start_time = datetime.strptime(args[0], "%H:%M").time()
                end_time = datetime.strptime(args[1], "%H:%M").time()
                self.notification_start = start_time
                self.notification_end = end_time
                return f"Notification hours set: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
            except ValueError:
                return "Invalid time format. Use: /notifications HH:MM HH:MM"
        else:
            return f"Current notification hours: {self.notification_start.strftime('%H:%M')} - {self.notification_end.strftime('%H:%M')}\nChange with: /notifications HH:MM HH:MM"

    def cmd_help(self, args):
        """Help Command"""
        return """Available commands:
/agenda - Show today's agenda
/subscribe - Subscribe to automatic notifications
/unsubscribe - Unsubscribe from notifications
/status - Show your subscription and whitelist status
/notifications [start end] - Show/set notification hours (HH:MM HH:MM)
/test-notification - Send test notification in 1 minute (subscribers only)
/whitelist [add|remove] <jid> - Manage whitelist (admin only)
/ping - Pong
/time - Current time
/help - This help"""

    def cmd_time(self, args):
        """Time Command"""
        current_time = datetime.now().strftime("%H:%M:%S")
        current_date = datetime.now().strftime("%Y-%m-%d")
        return f"Current time: {current_time}\nDate: {current_date}"

    def cmd_ping(self, args):
        """Ping Command"""
        return "Pong"

    def format_agenda(self, agenda: Dict[str, Any]) -> str:
        """Format agenda data into readable text"""
        now = datetime.now()
        result = [f"Agenda for {now.strftime('%Y-%m-%d %H:%M')}"]

        # Schedules today
        if agenda["schedules_today"]:
            result.append("\nScheduled for today:")
            for item in agenda["schedules_today"]:
                result.append(f"  - {item['title']} ({item['file_title']})")

        # Deadlines today
        if agenda["deadlines_today"]:
            result.append("\nDeadlines today:")
            for item in agenda["deadlines_today"]:
                result.append(f"  - {item['title']} ({item['file_title']})")

        # TODOs
        todos = agenda["todos"]
        if any(todos.values()):
            result.append("\nTasks:")
            for status in ["ACTIVE", "NEXT", "TODO", "WAIT"]:
                if todos[status]:
                    result.append(f"  {status}:")
                    for item in todos[status][:5]:  # Limit to 5 items per status
                        result.append(f"    - {item['title']}")
                    if len(todos[status]) > 5:
                        result.append(f"    ... and {len(todos[status]) - 5} more")

        if len(result) == 1:
            result.append("\nNo appointments or tasks for today!")

        return "\n".join(result)

    def is_notification_time(self) -> bool:
        """Check if current time is within notification hours"""
        current_time = datetime.now().time()
        return self.notification_start <= current_time <= self.notification_end

    async def periodic_agenda_notifications(self):
        """Send agenda notifications every 2 hours"""
        while True:
            try:
                if self.is_notification_time():
                    now = datetime.now()

                    # Check if we should send agenda (every 2 hours)
                    if (
                        self.last_agenda_sent is None
                        or (now - self.last_agenda_sent).total_seconds()
                        >= self.agenda_interval * 3600
                    ):

                        agenda = parse_org_agenda_items()
                        agenda_text = self.format_agenda(agenda)

                        # Send to all subscribers
                        await self.send_notification_to_subscribers(
                            f"Automatic agenda notification\n\n{agenda_text}"
                        )
                        self.last_agenda_sent = now

                # Check every 30 minutes
                await asyncio.sleep(30 * 60)

            except Exception as e:
                logging.error(f"Error in periodic notifications: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying

    async def schedule_deadline_notifications(self):
        """Handle schedule and deadline notifications"""
        while True:
            try:
                if self.is_notification_time():
                    agenda = parse_org_agenda_items()
                    now = datetime.now()

                    # Check schedules for notifications
                    for item in agenda["schedules_today"]:
                        if item["scheduled"]:
                            scheduled_datetime = datetime.combine(
                                item["scheduled"], time(9, 0)
                            )  # Default to 9 AM
                            await self.check_schedule_notifications(
                                item, scheduled_datetime, now
                            )

                    # Check deadlines
                    for item in agenda["deadlines_today"]:
                        if item["deadline"]:
                            deadline_datetime = datetime.combine(
                                item["deadline"], time(23, 59)
                            )  # End of day
                            await self.check_deadline_notifications(
                                item, deadline_datetime, now
                            )

                # Check every 15 minutes for schedule/deadline notifications
                await asyncio.sleep(15 * 60)

            except Exception as e:
                logging.error(f"Error in schedule/deadline notifications: {e}")
                await asyncio.sleep(60)

    async def check_schedule_notifications(
        self, item: Dict, scheduled_time: datetime, now: datetime
    ):
        """Check and send schedule notifications"""
        time_diff = scheduled_time - now
        total_minutes = time_diff.total_seconds() / 60

        notification_id = (
            f"schedule_{item['file_name']}_{item['title']}_{scheduled_time.isoformat()}"
        )

        # 2 hours before: every 30 minutes
        if 90 <= total_minutes <= 120:
            if f"{notification_id}_2h" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"Appointment in ~2 hours:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_2h")

        elif 60 <= total_minutes < 90:
            if f"{notification_id}_90m" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"Appointment in ~1.5 hours:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_90m")

        # 1 hour before: every 15 minutes
        elif 45 <= total_minutes < 60:
            if f"{notification_id}_1h" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"Appointment in ~1 hour:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_1h")

        elif 30 <= total_minutes < 45:
            if f"{notification_id}_45m" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"Appointment in ~45 minutes:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_45m")

        elif 15 <= total_minutes < 30:
            if f"{notification_id}_30m" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"Appointment in ~30 minutes:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_30m")

        elif 0 <= total_minutes < 15:
            if f"{notification_id}_15m" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"URGENT: Appointment in ~15 minutes:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_15m")

    async def check_deadline_notifications(
        self, item: Dict, deadline_time: datetime, now: datetime
    ):
        """Check and send deadline notifications"""
        time_diff = deadline_time - now
        total_hours = time_diff.total_seconds() / 3600

        notification_id = f"deadline_{item['file_name']}_{item['title']}_{deadline_time.date().isoformat()}"

        if 6 <= total_hours <= 8:
            if f"{notification_id}_today" not in self.sent_notifications:
                await self.send_notification_to_subscribers(
                    f"DEADLINE TODAY:\n{item['title']} ({item['file_title']})"
                )
                self.sent_notifications.add(f"{notification_id}_today")

    async def send_notification_to_subscribers(self, message: str):
        """Send notification message to all subscribers"""
        try:
            for subscriber in self.subscribers:
                self.send_message(mto=subscriber, mbody=message, mtype="chat")
        except Exception as e:
            logging.error(f"Error sending notification: {e}")


async def main_async():
    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
    from dotenv import load_dotenv

    load_dotenv()
    XMPP_ID = os.getenv("XMPP_ID")
    XMPP_PASS = os.getenv("XMPP_PASS")

    if not XMPP_ID or not XMPP_PASS:
        print("XMPP_ID and XMPP_PASS must be set in .env file")
        exit(1)

    xmpp = CommandBot(XMPP_ID, XMPP_PASS)
    xmpp.connect()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Bot shutting down...")
        xmpp.disconnect()
