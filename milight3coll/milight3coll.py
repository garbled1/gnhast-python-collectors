#!/usr/bin/env python3

import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast
from MilightWifiBridge import MilightWifiBridge


debug_mode = False


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Milight Collector')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/milight3coll.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store',
                        default='', help='Write out a config file and exit')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')
    parser.add_argument('--miip', type=str, action='store',
                        default='127.0.0.1', help='IP of milight controller')
    parser.add_argument('--miport', type=int, action='store',
                        default=5987, help='Milight port #')

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
    print('milight {', file=cf)
    print('  instance = 1', file=cf)
    print('  port = {0}'.format(str(args.miport)), file=cf)
    print('  ip = {0}'.format(args.miip), file=cf)
    print('  timeout = 5', file=cf)
    print('}', file=cf)
    print('misc {', file=cf)
    print('  logfile = "/usr/local/var/log/milight3coll.log"', file=cf)
    print('}', file=cf)

    cf.close()
    print("Wrote initial config file at {0}, connecting to gnhastd".format(args.conf))

    gn_conn = gnhast.gnhast(loop, args.conf)
    await gn_conn.gn_build_client('milight3coll')
    
    print("Connection established, wiring devices")

    zones = [ 0, 1, 2, 3, 4 ];
    mdevices = {
        'disco': 'switch',
        'color': 'switch',
        'brightness': 'dimmer',
        'saturation': 'dimmer',
        'temperature': 'dimmer',
        'onoff': 'switch'
    }
    print("Connecting to milight to get macaddr at {0}:{1}".format(args.miip, str(args.miport)))
    milight = MilightWifiBridge()
    if not milight.setup(ip=args.miip, port=args.miport, timeout_sec=5.0):
        print("Cannot connect to milight bridge!")
        loop.stop()
        exit(1)

    ma = milight.getMacAddress()
    macaddr = ma.replace(":", "")
    print("Macaddr = {0}".format(macaddr))
    
    # loop to create devices
    for z in zones:
        for d in mdevices.keys():
            duid = '{0}-zone{1}-{2}'.format(macaddr, str(z), d)
            dname = 'MiLight zone{0} {1}'.format(str(z), d)
            new_dev = gn_conn.new_device(duid, dname,
                                         gn_conn.cf_type.index(mdevices[d]),
                                         gn_conn.cf_subt.index('switch'))
            new_dev['proto'] = gn_conn.proto_map.index('light')
            new_dev['rrdname'] = 'milz{0}{1}'.format(str(z), d)

    print("Re-writing config file: {0}".format(args.conf))
    gn_conn.write_conf_file(args.conf)

    print("Disconnecting from gnhastd")
    await gn_conn.gn_disconnect()

    print("Config file written.")
    print("Edit it if needed, then restart collector")


async def register_devices(gn_conn):
    for dev in gn_conn.devices:
        await gn_conn.gn_register_device(dev)


async def coll_chg_cb(gn_conn, dev):
    """
    When we get a chg from gnhast, tell the device to do a thing
    """
    usplit = dev['uid'].split('-')
    mode = usplit[2]
    zone = int(usplit[1].split('e')[1])

    if 'onoff' in dev['uid']:
        if dev['data'] == 0: #off
            gn_conn.milight.turnOff(zoneId=zone)
        if dev['data'] == 1: #on
            gn_conn.milight.turnOn(zoneId=zone)
        return

    if 'disco' in dev['uid']:
        gn_conn.milight.setDiscoMode(discoMode=dev['data'], zoneId=zone)
        return

    if 'color' in dev['uid']:
        gn_conn.milight.setColor(color=dev['data'], zoneId=zone)
        return

    if 'brightness' in dev['uid']:
        gn_conn.milight.setBrightness(brightness=int(255*dev['data']),
                                      zoneId=zone)
    if 'saturation' in dev['uid']:
        gn_conn.milight.setSaturation(saturation=int(255*dev['data']),
                                      zoneId=zone)
    if 'temperature' in dev['uid']:
        gn_conn.milight.setTemperature(temperature=int(255*dev['data']),
                                      zoneId=zone)


        
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
    await gn_conn.gn_build_client('milight3coll')
    gn_conn.LOG("Milight3coll collector starting up")

    # Read the ip and port from the milight3coll section of the config file
    gn_conn.mi_ip = gn_conn.config['milight']['ip']
    gn_conn.mi_timeout = gn_conn.config['milight']['timeout']
    gn_conn.mi_port = gn_conn.config['milight']['port']
    if 'instance' in gn_conn.config['milight'].keys():
        gn_conn.instance = int(gn_conn.config['milight']['instance'])

    # Connect to the milight
    gn_conn.milight = MilightWifiBridge()
    if not gn_conn.milight.setup(ip=gn_conn.mi_ip, port=gn_conn.mi_port,
                         timeout_sec=gn_conn.mi_timeout):
        print("Cannot connect to milight bridge!")
        loop.stop()
        exit(1)

    gn_conn.mi_longmac = gn_conn.milight.getMacAddress()
    gn_conn.mi_macaddr = gn_conn.mi_longmac.replace(":", "")

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

    # These are write only devices.  Just wire up a chg callback
    gn_conn.coll_chg_cb = coll_chg_cb

    return


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    exit(0)
