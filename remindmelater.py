import os
import sys
from time import time
import pickle
import logging
from datetime import datetime, timezone, timedelta

import telegram.ext
from telegram import Update
from telegram.ext import Updater, CommandHandler, PicklePersistence, CallbackContext, Job, JobQueue
import pytz

import secret


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)


DATA_FILE = "data.pickle"
JOBS_FILE = "jobs.pickle"

JOB_DATA = ('callback', 'next_t', 'context', 'name')


def save_jobs_to_pickle(context):
    if isinstance(context, CallbackContext):
        jobs = context.job.context.jobs()
    else:
        jobs = context.jobs()
    with open(JOBS_FILE, "wb") as f:
        for job in jobs:
            if job.name == 'save_job':
                continue

            data = tuple(getattr(job, attr) for attr in JOB_DATA)

            pickle.dump(data, f)


def load_jobs_from_pickle(queue: JobQueue):
    with open(JOBS_FILE, 'rb') as f:
        while 1:
            try:
                data = pickle.load(f)
                queue.run_daily(data[0], data[1], context=data[2], name=data[3])
            except EOFError:
                break


def save_job(context):
    save_jobs_to_pickle(context)


def start(update: Update, context: CallbackContext):
    """ Sends a message when the /start command is used. """
    user = update.effective_user
    update.message.reply_markdown_v2(
        fr'Hi {user.mention_markdown_v2()}\!',
    )


def remove_job_if_exists(name: str, context: CallbackContext):
    """ Removes a job with a certain name if it exists. """
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def check_validity_of_time_string(time_str: str):
    """ Checks if the string is a valid HH:MM string. """
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False


def check_validity_of_date_string(date_str: str):
    """ Checks if the string is a valid DD.MM string. """
    try:
        datetime.strptime(date_str, "%d.%m")
        return True
    except ValueError:
        return False


def add_new_reminder(update: Update, context: CallbackContext):
    """ Adds a new reminder to a certain date. """
    try:
        if len(context.args) > 1:
            set_date_args = context.args[0]
            content_args = ""
            for s in context.args[1:]:
                content_args += (s + " ")
            if check_validity_of_date_string(set_date_args):
                set_date = datetime.strptime(set_date_args, "%d.%m")
                set_date = set_date.strftime("%d.%m")
                if set_date in context.user_data:
                    context.user_data[set_date].append(content_args)
                else:
                    context.user_data.update({set_date: [content_args]})
                update.message.reply_text("Added a reminder for " + set_date + " about " + content_args)
            else:
                update.message.reply_text("Couldn't parse the date, sorry")
                raise ValueError
        else:
            update.message.reply_text("Not enough arguments.")
            raise IndexError
    except (ValueError, IndexError):
        update.message.reply_text("Usage: /add <DD.MM> <content>")


def notes_to_str(day: str, notes: list):
    """ Helper function for formatting all the notes from a certain day. """
    string = "Here's everything that you planned on " + day + "\n"
    for note in notes:
        string += "\n" + note
    return string


def reminder(context: CallbackContext):
    """ Callback for the daily reminder function. """
    date_str = datetime.now(context.job.context["timezone"]).strftime("%d.%m")
    if date_str in context.job.context:
        context.bot.send_message(int(context.job.name), notes_to_str(date_str, context.job.context[date_str]))


def output_all_reminders(update: Update, context: CallbackContext):
    for k, v in context.user_data.items():
        if k == 'timezone':
            continue
        update.message.reply_text(notes_to_str(k, v))


def set_timezone_offset(update: Update, context: CallbackContext):
    """ Sets the timezone offset for a user and saves it to context.user_data. """
    try:
        tz_str = context.args[0]
        try:
            tz_offset = int(tz_str)
            tz_offset = timezone(timedelta(hours=tz_offset))
        except ValueError:
            update.message.reply_text("Couldn't parse the timezone, sorry!")
            raise ValueError from None
        context.user_data.update({"timezone": tz_offset})
        update.message.reply_text("Timezone set to " + str(context.user_data["timezone"]))

    except (ValueError, IndexError):
        update.message.reply_text("Usage: /set_timezone <+HH>")


def set_time_for_reminder(update: Update, context: CallbackContext):
    """ Sets the time for the daily reminder. """
    chat_id = update.message.chat_id
    try:
        set_time_args = context.args[0]
        if check_validity_of_time_string(set_time_args):
            set_time_local = datetime.strptime(set_time_args, "%H:%M").replace(tzinfo=context.user_data["timezone"])
            set_time = set_time_local.astimezone(pytz.UTC)
            remove_job_if_exists(str(chat_id), context)
            context.job_queue.run_daily(reminder, set_time.timetz(), context=context.user_data, name=str(chat_id))
            update.message.reply_text("Set the time to " + set_time_local.timetz().strftime("%H:%M (%z)"))
        else:
            update.message.reply_text("Couldn't parse the time, sorry!")
            raise ValueError

    except (IndexError, ValueError):
        update.message.reply_text("Usage: /set_time <HH:MM>")


def main():
    """ Starts the bot. """
    data_persistence = PicklePersistence(filename=DATA_FILE)
    updater = Updater(secret.http_api, persistence=data_persistence, use_context=True)
    dispatcher = updater.dispatcher

    updater.job_queue.run_repeating(save_job, timedelta(seconds=30), context=updater.job_queue)
    try:
        load_jobs_from_pickle(updater.job_queue)
    except FileNotFoundError:
        pass

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("set_time", set_time_for_reminder))
    dispatcher.add_handler(CommandHandler("add", add_new_reminder))
    dispatcher.add_handler(CommandHandler("all", output_all_reminders))
    dispatcher.add_handler(CommandHandler("set_timezone", set_timezone_offset))

    updater.start_polling()
    updater.idle()

    save_jobs_to_pickle(updater.job_queue)


if __name__ == "__main__":
    main()
