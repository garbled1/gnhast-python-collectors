#!/usr/bin/env python

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast
from influxdb import InfluxDBClient
import datetime

debug_mode = False
db_client = None
gn_conn = None


def parse_cmdline():
    parser = argparse.ArgumentParser(description='InfluxDB Collector')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/influxcoll.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store_true',
                        default='', help='Write out a config file and exit')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')
    parser.add_argument('--influxdb_name', type=str, action='store',
                        default='gnhast', help='Influx database name')
    parser.add_argument('--influxdb_host', type=str, action='store',
                        default='127.0.0.1', help='InfluxDB host')
    parser.add_argument('--influxdb_port', type=int, action='store',
                        default=8086, help='InfluxDB port #')
    parser.add_argument('--influxdb_user', type=str, action='store',
                        help='InfluxDB user name')
    parser.add_argument('--influxdb_pass', type=str, action='store',
                        help='InfluxDB user password')

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
    print('influxcoll {', file=cf)
    print('  # feed speed in seconds, 0 for a notification on change only.',
          file=cf)
    print('  feed = 0', file=cf)
    print('  recheck = 3600', file=cf)
    print('  host = {0}'.format(args.influxdb_host), file=cf)
    print('  port = {0}'.format(str(args.influxdb_port)), file=cf)
    print('  influxdb_name = {0}'.format(args.influxdb_name), file=cf)
    if args.influxdb_user and args.influxdb_pass:
        print('  user = {0}'.format(args.influxdb_user), file=cf)
        print('  pass = {0}'.format(args.influxdb_pass), file=cf)
    print('}', file=cf)
    print('misc {', file=cf)
    print('  logfile = "/usr/local/var/log/influxcoll.log"', file=cf)
    print('}', file=cf)
    cf.close()

    print("Wrote initial config file at {0}".format(args.conf))
    print("Now creating initial influxdb {0}".format(args.influxdb_name))

    if args.influxdb_user:
        db_client = InfluxDBClient(host=args.influxdb_host,
                                   port=args.influxdb_port,
                                   username=args.influxdb_user,
                                   password=args.influxdb_pass)
    else:
        db_client = InfluxDBClient(host=args.influxdb_host,
                                   port=args.influxdb_port)
    db_client.create_database(args.influxdb_name)
    db_client.close()

    print("Config file written and db created.")
    print("Edit it if needed, then restart collector")


async def ask_for_devicelist(gn_conn):
    """ Ask gnhast for a list of devices every hour
        Initialize a known_devs list too.
    """
    gn_conn.known_devs = []
    sleep_time = int(gn_conn.config['influxcoll']['recheck'])
    while True:
        gn_conn.LOG_DEBUG('Executing ldevs')
        await gn_conn.gn_ldevs()
        gn_conn.LOG_DEBUG('Sleeping for {0} seconds'.format(str(sleep_time)))
        await asyncio.sleep(sleep_time)


async def coll_reg_cb(dev):
    """ Gnhast responds with a reg for each device
        respond back to it asking for a feed or cfeed if it's new.
    """
    if dev['uid'] in gn_conn.known_devs:
        gn_conn.LOG_DEBUG('Ignoring known device {0}.'.format(dev['uid']))
    else:
        gn_conn.LOG('Got device {0} asking for a feed.'.format(dev['uid']))
        feedrate = int(gn_conn.config['influxcoll']['feed'])
        if feedrate > 0:
            await gn_conn.gn_feed_device(dev, feedrate)
        else:
            await gn_conn.gn_cfeed_device(dev)
            gn_conn.known_devs.append(dev['uid'])
        gn_conn.LOG('Asking for a full device dump')
        await gn_conn.gn_ask_device(dev, full=True)


async def coll_upd_cb(dev):
    """ Once we've issued a feed, now gnhast will send us updates.
        with each update, shove it into influxdb
    """
    gn_conn.LOG_DEBUG('Got data for {0} : {1}'.format(dev['uid'], dev['data']))
    measure = gn_conn.arg_by_subt[dev['subtype']]
    if dev['type'] == 2 and dev['subtype'] == 1:
        measure = 'dimmer'
    json_data = [
        {
            "measurement": measure,
            "tags": {
                "id": dev['uid'],
                "name": dev['name'],
                "type": gn_conn.cf_type[dev['type']],
                "proto": gn_conn.proto_map[dev['proto']]
            },
            "time": datetime.datetime.utcnow().isoformat() + 'Z',
            "fields": {
                "data": dev['data']
            }
        }
    ]
    if ('tags' in dev and len(dev['tags']) > 1):
        json_data[0]['tags'].update(zip(dev['tags'][::2], dev['tags'][1::2]))
    try:
        db_client.write_points(json_data)
    except:
        pass
            


async def main(loop):
    global debug_mode
    global db_client
    global gn_conn

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
    await gn_conn.gn_build_client('influxcoll')
    gn_conn.LOG("InfluxDB collector starting up")

    # Read the db info from the influx section of the config and connect

    if 'user' in gn_conn.config['influxcoll'] and 'pass' in gn_conn.config['influxcoll']:
        db_client = InfluxDBClient(host=gn_conn.config['influxcoll']['host'],
                                   port=gn_conn.config['influxcoll']['port'],
                                   username=gn_conn.config['influxcoll']['user'],
                                   password=gn_conn.config['influxcoll']['pass'])
    else:
        db_client = InfluxDBClient(host=gn_conn.config['influxcoll']['host'],
                                   port=gn_conn.config['influxcoll']['port'])

    db_list = db_client.get_list_database()
    if not any(d.get('name', None) == gn_conn.config['influxcoll']['influxdb_name'] for d in db_list):
        loop.stop()
        print('Cannot find DB named {0} in influx, create please.'.format(gn_conn.config['influxcoll']['influxdb_name']))
        return
    db_client.switch_database(gn_conn.config['influxcoll']['influxdb_name'])
        
    # set up a signal handler
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig,
                                lambda: asyncio.ensure_future(gn_conn.shutdown(sig, loop)))

    # log reopen on SIGHUP
    loop.add_signal_handler(signal.SIGHUP,
                            lambda: asyncio.ensure_future(gn_conn.log_open()))

    # fire up the listener and do gnhastly things..
    asyncio.ensure_future(gn_conn.gnhastd_listener())

    # wire up all the callbacks
    gn_conn.coll_reg_cb = coll_reg_cb
    gn_conn.coll_upd_cb = coll_upd_cb
    
    # Ask for a device list and begin the madness
    asyncio.ensure_future(ask_for_devicelist(gn_conn))
    return


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    exit(0)
