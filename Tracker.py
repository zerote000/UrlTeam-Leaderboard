import argparse

parser = argparse.ArgumentParser(description='Show statistics from the ArchiveTeam URLTeam tracker')
parser.add_argument('--nickname', '-n', type=str, help='Your nickname used for the tracker', default='Zerote')
parser.add_argument('--time', '-t', type=float, help='Refresh interval for the user interface (in seconds)', default=1.0)
parser.add_argument('--solo', '-s', action='store_true', help='Show only the stats of the user selected with -n')
parser.add_argument('--foundlinks', '-f', action='store_true', help='Show the number of found links')
args = parser.parse_args()

import json
import websocket
import os
import pandas as pd
import numpy as np
import threading
import datetime
import msvcrt
from queue import Queue
from Utils import get_intersection
import signal
signal.signal(signal.SIGINT, signal.SIG_DFL)
try:
    import thread
except ImportError:
    import _thread as thread
import time


def cls():
    os.system('cls' if os.name == 'nt' else 'clear')


def process_data():
    while True:
        drop = ['started', 'project']
        if not args.foundlinks:
            drop.append('found')

        message = message_queue.get()
        parsed_message = json.loads(message)
        global lifetime_df
        global live_df
        global rate_df
        global start

        if len(parsed_message) == 4:
            lifetime = parsed_message['lifetime']

            lifetime_df = pd.DataFrame.from_dict(lifetime).T
            if args.foundlinks:
                lifetime_df['found'] = lifetime_df[0]
            lifetime_df['scanned'] = lifetime_df[1]
            lifetime_df['scans_last_hour'] = 0
            lifetime_df = lifetime_df.drop([0, 1], axis=1)

            live = parsed_message['live']

            live_df = pd.DataFrame(live).drop(drop, axis=1)

            handle_updates(live_df)

        else:
            live = parsed_message['live_new']
            update = pd.DataFrame([live]).drop(drop, axis=1)
            handle_updates(update)

        message_queue.task_done()


def handle_updates(update, update_total_scans=True):
    for _, update in update.iterrows():
        if not update['username'] in lifetime_df.index:
            lifetime_df.loc[update['username']] = [0, 0]

        user = lifetime_df.loc[update['username']]
        user['scans_last_hour'] += update['scanned']
        if update_total_scans:
            user['scanned'] += update['scanned']
        if args.foundlinks:
            user['found'] += update['found']


def update_user_rates():
    running_time = time.time() - start
    multiplier = 1 / (running_time / 3600)

    my_scans = lifetime_df.loc[args.nickname]['scanned']
    my_rate = lifetime_df.loc[args.nickname]['scans_last_hour'] * multiplier
    my_scans_plus_rate = my_scans + my_rate
    my_line = [[0, my_scans], [60, my_scans_plus_rate]]

    global rate_df
    rate_df = lifetime_df.copy()
    rate_df['scans_per_hour'] = 0
    rate_df['time_until_takeover'] = 0

    rate_df['scans_per_hour'] = rate_df['scans_last_hour'].values * multiplier
    rate_df = rate_df.astype(np.int64)

    my_index = rate_df.index.get_loc(args.nickname)
    my_scan_rate = rate_df.iloc[my_index]['scans_per_hour']
    if my_scan_rate == 0:
        return

    rate_df['time_until_takeover'] = get_intersection(my_line, rate_df['scanned'].values, rate_df['scans_per_hour'].values)
    rate_df['time_until_takeover'] = rate_df['time_until_takeover'].replace([np.inf, -np.inf], np.nan)
    rate_df = rate_df.fillna(0)
    rate_df = rate_df.astype(np.int64)


def print_update():
    threading.Timer(args.time, print_update).start()
    global rate_df
    global offset
    global top_k
    if lifetime_df is not None:
        terminal_size = os.get_terminal_size()
        top_k_max = terminal_size.lines - 4
        if msvcrt.kbhit():
            key = ord(msvcrt.getch())
            if key == 224:
                key = ord(msvcrt.getch())
                if key == 80: #Down arrow
                    offset += 10
                elif key == 72: #Up arrow
                    offset -= 10
            elif key == 114: #R key
                offset = 1
                top_k = 10
            elif key == 43: #+ key
                top_k += 5
            elif key == 45: #- key
                top_k -= 5
                top_k = 0 if top_k < 0 else top_k
        top_k = top_k_max if top_k > top_k_max else top_k

        start_time = time.time()
        update_user_rates()
        

        rate_df = rate_df.sort_values(by='scanned', ascending=False)

        my_index = rate_df.index.get_loc(args.nickname)

        my_scans = rate_df.iloc[my_index]['scanned']

        string_to_print = ''
        if args.foundlinks:
            found_string = '            | Scanned'
        else:
            found_string = ''
        string_to_print += f'Place | Name                 | Scanned    | Distance   | Scans/hr   | Take over{found_string}\n'

        def format_line(index):
            user = rate_df.iloc[index]
            time_until_takeover = str(datetime.timedelta(minutes=int(user["time_until_takeover"])))[:-3] if user["time_until_takeover"] > 0 else 'N/A'
            if args.foundlinks:
                found_string = f' | {user["found"]:10}'
            else:
                found_string = ''
            return f'{index+1:5} | {user.name:20} | {user["scanned"]:10} | {user["scanned"]-my_scans:10} | {user["scans_per_hour"]:10} | {time_until_takeover:20}{found_string}\n'

        space_left = terminal_size.lines - (3)

        spacer_width = 90
        if args.foundlinks:
            spacer_width += 13
        if args.solo:
            space_left = 0
            offset = 1

        if not args.solo:
            # Prints top-k users stats
            for index in list(range(top_k)):
                string_to_print += format_line(index)
            space_left -= top_k
            
            # If top-k is 0, don't print separater
            if top_k > 0:
                string_to_print += f'{"-" * spacer_width}\n'
                space_left -= 1

        end_offset = 0
        start_offset = 0
        if offset > space_left:
            end_offset = 0
            start_offset = 1
            string_to_print += format_line(my_index)
            string_to_print += f'{"-" * spacer_width}\n'
            space_left -= 1
        elif offset < 1:
            end_offset = -1
            start_offset = 0
            space_left -= 1
        
        if not args.solo:
            # Prints selected user (in some cases) and fills remaining space with users below
            for index in list(range(my_index - (space_left - offset - start_offset), my_index + (offset + end_offset))):
                string_to_print += format_line(index)

            if offset < 1:
                string_to_print += f'{"-" * spacer_width}\n'
                string_to_print += format_line(my_index)


        end_time = time.time() - start_time
        if not args.solo:
            string_to_print += f'Use UP and DOWN arrows to navigate leaderboard, + and - to adjust top-k size, r to reset\n'
        string_to_print += f'Queue:{message_queue.qsize()}     Calculating took {end_time:.3f}s'
        cls()
        print(string_to_print, end='')


def on_message(ws, message):
    message_queue.put(message)


def on_error(ws, error):
    print(error)


def on_close(ws):
    print("### closed ###")


def on_open(ws):
    def run(*args):
        for i in range(3):
            time.sleep(1)
            ws.send("Hello %d" % i)
        time.sleep(1)
        ws.close()
        print("thread terminating...")

    threading.Thread(target=run)


if __name__ == "__main__":
    start = time.time()
    lifetime_df = None
    live_df = None
    rate_df = None
    message_queue = Queue()

    top_k = 10
    offset = 1
    threads = []
    t = threading.Thread(target=process_data)
    t.start()
    threads.append(t)

    print_update()

    websocket.enableTrace(True)
    ws = websocket.WebSocketApp("wss://tracker.archiveteam.org:1338/api/live_stats",
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.on_open = on_open
    ws.run_forever()
