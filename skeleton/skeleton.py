#!/usr/bin/env python

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast


debug_mode = False


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Skeleton Collector')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/skeleton.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store',
                        default='', help='Write out a config file and exit')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')

    args = parser.parse_args()
    return args


async def poll_sensor(gn_conn, poll_time):
    test_dev = gn_conn.find_dev_byuid('testdev')

    if test_dev is None:
        gn_conn.LOG_ERROR("Cannot find devices")
        await gn_conn.shutdown(signal.SIGTERM, gn_conn.loop)

    while True:
        # set some values for the device
        cur_time = int(time.time())
        test_dev['data'] = 7
        test_dev['lastupd'] = cur_time

        # tell gnhast about the values
        await gn_conn.gn_update_device(test_dev)

        # sleep for awhile
        await asyncio.sleep(poll_time)


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
    print('skeleton {', file=cf)
    print('  update = 5', file=cf)
    print('}', file=cf)
    print('misc {', file=cf)
    print('  logfile = "/usr/local/var/log/influxcoll.log"', file=cf)
    print('}', file=cf)

    cf.close()
    print("Wrote initial config file at {0}, connecting to gnhastd".format(args.conf))

    gn_conn = gnhast.gnhast(loop, args.conf)
    await gn_conn.gn_build_client('skeleton')

    print("Connection established, wiring devices")
    test_dev = gn_conn.new_device('testdev', 'Skeleton Test Device',
                                  gn_conn.cf_type.index('sensor'),
                                  gn_conn.cf_subt.index('number'))
    test_dev['rrdname'] = test_dev['name'].replace(' ', '_')[:20]

    print("Re-writing config file: {0}".format(args.conf))
    gn_conn.write_conf_file(args.conf)

    print("Disconnecting from gnhastd")
    await gn_conn.gn_disconnect()

    print("Config file written.")
    print("Edit it if needed, then restart collector")


async def register_devices(gn_conn):
    for dev in gn_conn.devices:
        await gn_conn.gn_register_device(dev)


async def main(loop):
    global debug_mode

    try:
        args = parse_cmdline()
    except SystemExit:
        loop.stop()
        return

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
    await gn_conn.gn_build_client('skeleton')
    gn_conn.LOG("Skeleton collector starting up")

    # Read the update value from the skeleton section of the config file
    poll_time = gn_conn.config['skeleton']['update']

    # set up a signal handler
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig,
                                lambda: asyncio.ensure_future(gn_conn.shutdown(sig, loop)))
    # log reopen on SIGHUP
    loop.add_signal_handler(signal.SIGHUP,
                            lambda: asyncio.ensure_future(gn_conn.log_open()))

    # fire up the listener and do gnhastly things..
    asyncio.ensure_future(gn_conn.gnhastd_listener())
    asyncio.ensure_future(register_devices(gn_conn))

    # poll your sensor for data
    gn_conn.LOG('starting poller')
    asyncio.ensure_future(poll_sensor(gn_conn, poll_time))
    return


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    exit(0)
