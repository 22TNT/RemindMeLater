import pickle
import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import Updater, CommandHandler, PicklePersistence, CallbackContext, JobQueue
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
    """ Pickles all active jobs into JOBS_FILE. """
    if isinstance(context, CallbackContext):
        jobs = context.job.context.jobs()
    else:
        jobs = context.jobs()
    with open(JOBS_FILE, "wb") as f:
        for job in jobs:
            if job.name != 'save_job':
                data = tuple(getattr(job, attr) for attr in JOB_DATA)
                pickle.dump(data, f)


def load_jobs_from_pickle(queue: JobQueue):
    """ Unpickles jobs from JOBS_FILE and creates new jobs with given arguments. """
    with open(JOBS_FILE, 'rb') as f:
        while 1:
            try:
                data = pickle.load(f)
                args = [x for x in data]
                if args[3].endswith("-once"):
                    queue.run_once(data[0], data[1], context=data[2], name=data[3])
                else:
                    queue.run_daily(data[0], data[1], context=data[2], name=data[3])
            except EOFError:
                break


def save_job(context):
    """ Wrapper for save_jobs_to_pickle(). """
    save_jobs_to_pickle(context)


def start(update: Update, context: CallbackContext):
    """ Sends a message when the /start command is used. """
    context.user_data.update({'chat_id': update.message.chat_id})
    context.user_data.update({'timezone': pytz.UTC})
    update.message.reply_text("Hi! I'm RemindPy, a bot to help you keep track of things.")
    update.message.reply_text("First, use /set_timezone to, well, set your timezone!")
    update.message.reply_text("After that, just use /set_time to set the time of your daily reminder " +
                              "and /add to add new reminders. \nYou can check out other commands with /help")


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
        context.bot.send_message(context.job.context['chat_id'], notes_to_str(date_str, context.job.context[date_str]))
        context.job.context.pop(date_str)


def output_all_reminders(update: Update, context: CallbackContext):
    """ Sends all reminders to the user. """
    f = False
    for k, v in context.user_data.items():
        if check_validity_of_date_string(k):
            f = True
            update.message.reply_text(notes_to_str(k, v))
    if not f:
        update.message.reply_text("You don't have any reminders")


def set_timezone_offset(update: Update, context: CallbackContext):
    """ Sets the timezone offset for a user and saves it to context.user_data["timezone"]. """
    try:
        tz_str = context.args[0]
        try:
            tz_offset = int(tz_str)
            tz_offset = timezone(timedelta(hours=tz_offset))
        except ValueError:
            update.message.reply_text("Couldn't parse the timezone, sorry!")
            raise ValueError from None
        context.user_data.update({"timezone": tz_offset})
        update.message.reply_text("Timezone set to " + str(context.user_data["timezone"]) +
                                  "\nWe advise you to /set_time again, just to be sure")

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


def delete_reminders_on_day(update: Update, context: CallbackContext):
    """ Deletes all reminders on a certain day. """
    try:
        del_date_args = context.args[0]
        if check_validity_of_date_string(del_date_args):
            if del_date_args in context.user_data:
                context.user_data.pop(del_date_args)
                update.message.reply_text("Successfully deleted all reminders on " + del_date_args)
            else:
                update.message.reply_text("No reminders that day anyway")
        else:
            update.message.reply_text("Couldn't parse the date, sorry!")

    except (ValueError, IndexError):
        update.message.reply_text("Usage: /del <DD.MM>")


def check_reminders_on_day(update: Update, context: CallbackContext):
    """ Outputs all reminders on a day, or prints out that there are no reminders on that day. """
    try:
        check_date_args = context.args[0]
        if check_validity_of_date_string(check_date_args):
            if check_date_args in context.user_data:
                update.message.reply_text(notes_to_str(check_date_args, context.user_data[check_date_args]))
            else:
                update.message.reply_text("Nothing planned on " + check_date_args)
        else:
            update.message.reply_text("Couldn't parse the date, sorry!")
    except (ValueError, IndexError):
        update.message.reply_text("Usage: /check <DD.MM>")


def help_message(update: Update, context: CallbackContext):
    """ Outputs a list of all available commands and their syntax. """
    update.message.reply_text("Here are all available commands:\n"
                              "/set_timezone <HH> - sets your timezone to a certain offset from UTC\n"
                              "/set_time <HH:MM> - sets your daily reminder time\n"
                              "/add <DD.MM> <content> - adds a reminder to a certain date\n"
                              "/del <DD.MM> - deletes all reminders on a certain date\n"
                              "/check <DD.MM> - outputs all reminders from a certain date\n"
                              "/all - outputs all reminders from all dates\n"
                              "/timer <HH:MM> <content> - creates a timed message\n"
                              "/timer_check - checks the contents of all timed messages\n"
                              "/timer_stop - stops all active timed messages\n"
                              "/help - this command")


def run_timed_message(context: CallbackContext):
    """ Callback function for set_timed_message(). """
    context.bot.send_message(context.job.context[0], text="You asked to remind you about "
                             + str(context.job.context[1]))


def set_timed_message(update: Update, context: CallbackContext):
    """ Creates a job that outputs a user-defined message in a certain time. """
    try:
        time_str = context.args[0]
        content_args = context.args[1]
        for s in context.args[2:]:
            content_args += (" " + s)
        if check_validity_of_time_string(time_str):
            time = datetime.strptime(time_str, "%H:%M")
            time = timedelta(hours=time.hour, minutes=time.minute)
            context.job_queue.run_once(run_timed_message,
                                       datetime.now(pytz.UTC) + time,
                                       (context.user_data['chat_id'], content_args),
                                       name=str(context.user_data['chat_id'])+'-once')
            update.message.reply_text("Created a timed message about " + content_args
                                      + " that will run in " + str(int(time.total_seconds())) + " seconds from now")
        else:
            update.message.reply_text("Couldn't parse the time, sorry")
            raise ValueError
    except (ValueError, IndexError):
        update.message.reply_text("Usage: /timer <HH:MM> <content>")


def check_all_timers(update: Update, context: CallbackContext):
    """ Outputs the context of all active run_once jobs. """
    if not context.job.job_queue.get_jobs_by_name(context.user_data['chat_id']+'-once'):
        update.message.reply_text("You don't have any active timers")
        return None
    string = "Here is everything you planned using /timer: \n"
    for job in context.job_queue.get_jobs_by_name(context.user_data['chat_id']+'-once'):
        string += "\n" + job.context[1]
    update.message.reply_text(string)
    return None


def stop_all_timers(update: Update, context: CallbackContext):
    """ Kills all active run_once jobs. """
    removed = remove_job_if_exists(context.user_data['chat_id']+'-once', context)
    if removed:
        update.message.reply_text("Removed all active timed messages")
    else:
        update.message.reply_text("You don't have any active timed messages")


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
    dispatcher.add_handler(CommandHandler("help", help_message))
    dispatcher.add_handler(CommandHandler("del", delete_reminders_on_day))
    dispatcher.add_handler(CommandHandler("check", check_reminders_on_day))
    dispatcher.add_handler(CommandHandler("timer", set_timed_message))
    dispatcher.add_handler(CommandHandler("timer_check", check_all_timers))
    dispatcher.add_handler(CommandHandler("timer_stop", stop_all_timers))

    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
