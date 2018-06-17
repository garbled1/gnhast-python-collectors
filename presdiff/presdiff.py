#!/usr/bin/env python

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast


debug_mode = False
gn_conn = None


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Pressure Differential Collector')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/presdiff.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store',
                        default='', help='Write out a config file and exit')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')
    parser.add_argument('--poll_time', type=int, action='store',
                        default=5, help='Poll time')

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
    print('presdiff {', file=cf)
    print('  update = {0}'.format(str(args.poll_time)), file=cf)
    print('  refuid = ""', file=cf)
    print('  compuid = ""', file=cf)
    print('}', file=cf)
    cf.close()
    print("Wrote initial config file at {0}, connecting to gnhastd".format(args.conf))

    gn_conn = gnhast.gnhast(loop, args.conf)
    await gn_conn.gn_build_client('presdiff')

    print("Connection established")
    print("Re-writing config file: {0}".format(args.conf))
    gn_conn.write_conf_file(args.conf)

    print("Disconnecting from gnhastd")
    await gn_conn.gn_disconnect()

    print("Config file written.")
    print("Edit it to fill in refuid and compuid, then restart collector")


async def _coll_reg_cb(dev):
    gn_conn.LOG('Got device {0} asking for feed.'.format(dev['uid']))
    await gn_conn.gn_feed_device(dev, gn_conn.config['presdiff']['update'])
    await gn_conn.gn_ask_device(dev)


# stupid hack to bounce arount the async wait thing
def coll_reg_cb(dev):
    loop = asyncio.get_event_loop()
    loop.create_task(_coll_reg_cb(dev))


def coll_upd_cb(dev):
    gn_conn.LOG('Got data for {0} : {1}'.format(dev['uid'], dev['data']))

    
async def main(loop):
    global debug_mode
    global gn_conn
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
    await gn_conn.gn_build_client('presdiff')
    gn_conn.LOG("Pressure Differential collector starting up")

    # Read the update value from the skeleton section of the config file
    poll_time = gn_conn.config['presdiff']['update']
    refuid = gn_conn.config['presdiff']['refuid']
    compuid = gn_conn.config['presdiff']['compuid']

    if compuid == '' or refuid == '':
        gn_conn.LOG_ERROR('compuid or refuid not specified sanely')
        loop.stop()
        return

    # set up a signal handler
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig,
                                lambda: asyncio.ensure_future(gn_conn.shutdown(sig, loop)))

    # fire up the listener and do gnhastly things..
    asyncio.ensure_future(gn_conn.gnhastd_listener())

    # wire up callbacks
    gn_conn.coll_reg_cb = coll_reg_cb
    gn_conn.coll_upd_cb = coll_upd_cb
    
    # poll your sensor for data
    gn_conn.LOG('Asking gnhast for data on sensors')
    await gn_conn.gn_ldevs(refuid)
    await gn_conn.gn_ldevs(compuid)

    return


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    exit(0)
