#!/usr/bin/env python
#
# Super simple collector that watches for alarms, and prints them to the
# console with pretty colors for severity.  Good example of the alarm callback
#

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast
from gnhast.gnhast import AlarmChan
from colorama import init, deinit
from colorama import Fore, Back, Style


debug_mode = False


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Alarm Console')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/alarmconsole.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store',
                        default='', help='Write out a config file and exit')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')
    parser.add_argument('--minsev', type=int, action='store',
                        default=1, help='Minimum severity of alarms to listen')
    parser.add_argument('--channels', nargs='+', help='Channels to listen to')
    
    args = parser.parse_args()
    return args


async def initial_setup(args, loop):
    print("This is your first run of the collector, setting up")
    print("Using gnhast server at {0}:{1}".format(args.server, str(args.port)))
    try:
        cf = open(args.conf, 'w')
    except PermissionError as error:
        print('ERROR: Cannot open {0} for writing'.format(args.conf))
        print('ERROR: {0}'.format(error))
        exit(1)

    print('gnhastd {', file=cf)
    print('  hostname = "{0}"'.format(args.server), file=cf)
    print('  port = {0}'.format(str(args.port)), file=cf)
    print('}', file=cf)
    print('', file=cf)
    print('alarmconsole {', file=cf)
    print('  minsev = {0}'.format(str(args.minsev)), file=cf)
    
    channels = 0
    if args.channels:
        for ch in args.channels:
            channels |= int(AlarmChan.from_str(ch))
    else:
        channels = int(AlarmChan.ALL)
    print('  channels = {0}'.format(channels), file=cf)

    print('}', file=cf)
    cf.close()
    print("Wrote initial config file at {0}, connecting to gnhastd".format(args.conf))

    gn_conn = gnhast.gnhast(loop, args.conf)
    await gn_conn.gn_build_client('alarmconsole')

    print("Re-writing config file: {0}".format(args.conf))
    gn_conn.write_conf_file(args.conf)

    print("Disconnecting from gnhastd")
    await gn_conn.gn_disconnect()

    print("Config file written.")
    print("Edit it if needed, then restart collector")


async def register_devices(gn_conn):
    for dev in gn_conn.devices:
        await gn_conn.gn_register_device(dev)


def coll_alarm_cb(alarm):
    sev = int(alarm['alsev'])
    color = Fore.GREEN
    if sev < 10:
        color = Fore.GREEN + Style.DIM
    elif sev >= 10 and sev < 20:
        color = Fore.GREEN + Style.BRIGHT
    elif sev >= 20 and sev < 35:
        color = Fore.YELLOW + Style.DIM
    elif sev >= 35 and sev < 55:
        color = Fore.YELLOW + Style.BRIGHT
    elif sev >= 55 and sev < 75:
        color = Fore.RED + Style.DIM
    else:
        color = Fore.RED + Style.BRIGHT

    myflag = AlarmChan(int(alarm['alchan']))
        
    string = Style.RESET_ALL + 'Sev' + color + ' {0:2d}'.format(sev)
    string += Style.RESET_ALL
    string += '/{0:12s} '.format(myflag.to_simple_str())
    string += 'ALARM: {0:10s}'.format(alarm['aluid'])
    string += color + ' {0:41s}'.format(alarm['altext'])
    string += Style.RESET_ALL

    if sev == 0:
        string = Fore.GREEN + 'ALARM: {0} CLEARED'.format(alarm['aluid'])
        string += Style.RESET_ALL
    
    print(string)

        
async def main(loop):
    global debug_mode
    args = parse_cmdline()
    if args.debug:
        debug_mode = args.debug

    # look for a config file, if it doesn't exist, build a generic one
    if not os.path.isfile(args.conf):
        await initial_setup(args, loop)
        loop.stop()
        return

    # instantiate the gnhast class with the conf file as an argument
    gn_conn = gnhast.gnhast(loop, args.conf)
    gn_conn.debug = debug_mode

    # connect to gnhast
    await gn_conn.gn_build_client('alarmconsole')
    gn_conn.LOG("alarmconsole collector starting up")

    minsev = gn_conn.config['alarmconsole']['minsev']
    channels = gn_conn.config['alarmconsole']['channels']

    # set up a signal handler
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig,
                                lambda: asyncio.ensure_future(gn_conn.shutdown(sig, loop)))

    # fire up the listener and do gnhastly things..
    asyncio.ensure_future(gn_conn.gnhastd_listener())
    asyncio.ensure_future(register_devices(gn_conn))

    # attach my callback
    gn_conn.coll_alarm_cb = coll_alarm_cb
    
    await gn_conn.gn_listenalarms(minsev, channels)
    await gn_conn.gn_dumpalarms(alsev=minsev, alchan=channels)
    return


if __name__ == "__main__":
    init()
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    deinit()
    exit(0)
