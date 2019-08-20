#!/usr/bin/env python3

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast


debug_mode = False
gn_conn = None
refuid = ''
compuid = ''
diffuid = ''


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

    print("Connection established, wiring devices")

    diff_dev = gn_conn.new_device('presdiff', 'Pressure Difference',
                                 gn_conn.cf_type.index('sensor'),
                                 gn_conn.cf_subt.index('pressure'))
    diff_dev['rrdname'] = diff_dev['name'].replace(' ', '_')[:20]
    # calculated type
    diff_dev['proto'] = 16


    print("Re-writing config file: {0}".format(args.conf))
    gn_conn.write_conf_file(args.conf)

    print("Disconnecting from gnhastd")
    await gn_conn.gn_disconnect()

    print("Config file written.")
    print("Edit it to fill in refuid and compuid, then restart collector")


async def coll_reg_cb(dev):
    gn_conn.LOG('Got device {0} asking for feed.'.format(dev['uid']))
    await gn_conn.gn_feed_device(dev, gn_conn.config['presdiff']['update'])
    await gn_conn.gn_ask_device(dev)


async def coll_upd_cb(dev):
    cur_time = int(time.time())
    max_skew = gn_conn.config['presdiff']['update'] * 5
    gn_conn.LOG_DEBUG('Got data for {0} : {1}'.format(dev['uid'], dev['data']))
    if dev['uid'] == compuid:
        refdev = gn_conn.find_dev_byuid(refuid)
        if refdev is None:
            gn_conn.LOG_ERROR('Cannot find refdev!')
            gn_conn.collector_is_healthy = False
            return
        compdev = dev
        skew = cur_time - refdev['lastupd']
        if skew > max_skew:
            gn_conn.LOG_WARNING('Refdev last update is too old: {0}'.format(skew))
            gn_conn.collector_is_healthy = False
            return
    elif dev['uid'] == refuid:
        compdev = gn_conn.find_dev_byuid(compuid)
        if compdev is None:
            gn_conn.LOG_ERROR('Cannot find compdev!')
            gn_conn.collector_is_healthy = False
            return
        refdev = dev
        skew = cur_time - compdev['lastupd']
        if skew > max_skew:
            gn_conn.LOG_WARNING('compdev last update is too old: {0}'.format(skew))
            gn_conn.collector_is_healthy = False
            return

    # Now we have both devices and they are happy, let us compare
    pressure_diff = refdev['data'] - compdev['data']
    gn_conn.LOG_DEBUG('Pressure Diff: {0:2f}'.format(pressure_diff))

    pdev = gn_conn.find_dev_byuid(diffuid)
    if pdev is None:
        gn_conn.LOG_ERROR('Cannot find pressure diff device')
        return
    pdev['data'] = pressure_diff
    await gn_conn.gn_update_device(pdev)


async def register_devices(gn_conn):
    global diffuid
    # because we call this before the ldevs, and we only have one dev,
    # this works...
    for dev in gn_conn.devices:
        await gn_conn.gn_register_device(dev)
        diffuid = dev['uid']


async def main(loop):
    global debug_mode
    global gn_conn
    global refuid
    global compuid

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

    # Read the update value from the presdiff section of the config file
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
    asyncio.ensure_future(register_devices(gn_conn))

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
