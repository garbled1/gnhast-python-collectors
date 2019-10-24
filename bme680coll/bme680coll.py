#!/usr/bin/env python3

import bme680
import time
import argparse
import asyncio
import signal
import os.path
from gnhast import gnhast


debug_mode = False
gas_baseline = 0


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Collect data from a BME680 i2c Sensor')

    parser.add_argument('-c', '--conf', type=str, action='store',
                        default='/usr/local/etc/bme680coll.conf',
                        help='Path to config file')
    parser.add_argument('-d', '--debug', action='store_true', default=False,
                        help='Debug mode')
    parser.add_argument('-m', '--dumpconf', action='store',
                        default='', help='Write out a config file and exit')
    parser.add_argument('-a', '--address', type=str, action='store',
                        default='0x76', help='i2c address of BME680')
    parser.add_argument('-b', '--burn_in', type=int, action='store',
                        default=300, help='Seconds to warm up gas sensor')
    parser.add_argument('-p', '--poll_time', type=int, action='store',
                        default=5, help='How often in seconds to poll sensor')
    parser.add_argument('-u', '--uid_prefix', type=str, action='store',
                        default='', help='Prefix for UID')
    parser.add_argument('--server', type=str, action='store',
                        default='127.0.0.1', help='Hostname of gnhastd server')
    parser.add_argument('--port', type=int, action='store',
                        default=2920, help='Port gnhastd listens on')

    args = parser.parse_args()
    return args


def init_bme680(bme_addr):
    try:
        sensor = bme680.BME680(i2c_addr=bme_addr)
        sensor.set_humidity_oversample(bme680.OS_2X)
        sensor.set_pressure_oversample(bme680.OS_1X)
        sensor.set_temperature_oversample(bme680.OS_8X)
        sensor.set_filter(bme680.FILTER_SIZE_0)
        sensor.set_gas_status(bme680.ENABLE_GAS_MEAS)
        sensor.set_gas_heater_temperature(320)
        sensor.set_gas_heater_duration(150)
        sensor.select_gas_heater_profile(0)
        return sensor
    except Exception:
        gn_conn.LOG_ERROR("Cannot initialize BME680 at addr {0}".format(str(bme_addr)))
        return None

async def burn_in_sensor(sensor, burn_in_time, gn_conn):
    start_time = time.time()
    curr_time = time.time()
    burn_in_data = []
    global gas_baseline

    while curr_time - start_time < burn_in_time:
        curr_time = time.time()
        if sensor.get_sensor_data() and sensor.data.heat_stable:
            gas = sensor.data.gas_resistance
            burn_in_data.append(gas)
            gn_conn.LOG_DEBUG("Gas: {0:.2f} Ohms  Time:{1:.2f}".format(gas, curr_time - start_time))
        await asyncio.sleep(1)

    gas_baseline = sum(burn_in_data[-50:]) / 50.0
    gn_conn.LOG_DEBUG("Computed gas baseline: {0} Ohms".format(gas_baseline))

    return


async def poll_sensor(gn_conn, sensor, poll_time, uid_prefix):
    gas_dev = gn_conn.find_dev_byuid(uid_prefix + 'gas')
    hum_dev = gn_conn.find_dev_byuid(uid_prefix + 'humid')
    temp_dev = gn_conn.find_dev_byuid(uid_prefix + 'temp')
    pres_dev = gn_conn.find_dev_byuid(uid_prefix + 'pres')

    if gas_dev is None or hum_dev is None or temp_dev is None or pres_dev is None:
        gn_conn.LOG_ERROR("Cannot find devices")
        await gn_conn.shutdown(signal.SIGTERM, gn_conn.loop)

    while True:
        if sensor.get_sensor_data() and sensor.data.heat_stable:
            gas = sensor.data.gas_resistance
            hum = sensor.data.humidity
            # When the gas sensor is running, the temp is high by 2 deg C
            temp = sensor.data.temperature - 2.0
            send_temp = temp
            if gn_conn.config['bme680coll']['tscale'] != 1:
                send_temp = gn_conn.gn_scale_temp(temp, 1, gn_conn.config['bme680coll']['tscale'])
            pressure = sensor.data.pressure
            cur_time = int(time.time())

            gas_dev['data'] = int(gas)
            gas_dev['lastupd'] = cur_time
            hum_dev['data'] = hum
            hum_dev['lastupd'] = cur_time
            temp_dev['data'] = send_temp
            temp_dev['lastupd'] = cur_time
            pres_dev['data'] = pressure
            pres_dev['lastupd'] = cur_time

            gn_conn.LOG_DEBUG('Gas:{0:.2f} Humid:{1:.2f} Temp:{2:.2f} Pres:{3:.2f}'.format(gas, hum, send_temp, pressure))

            gn_conn.collector_healthy = True
            await gn_conn.gn_update_device(gas_dev)
            await gn_conn.gn_update_device(hum_dev)
            await gn_conn.gn_update_device(temp_dev)
            await gn_conn.gn_update_device(pres_dev)

        else:
            gn_conn.LOG_WARNING("Sensors not operating")
            gn_conn.collector_healthy = False

        await asyncio.sleep(poll_time)


async def initial_setup(args, uid_prefix, loop):
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
    print('bme680coll {', file=cf)
    print('  update = {0}'.format(str(args.poll_time)), file=cf)
    print('  tscale = C', file=cf)
    print('  i2c_addr = "{0}"'.format(args.address), file=cf)
    print('  burn_in = {0}'.format(str(args.burn_in)), file=cf)
    print('}', file=cf)
    cf.close()
    print("Wrote initial config file at {0}, connecting to gnhastd".format(args.conf))

    gn_conn = gnhast.gnhast(loop, args.conf)
    await gn_conn.gn_build_client('BME680-{0}'.format(args.address))

    print("Connection established, wiring devices")
    gas_dev = gn_conn.new_device(uid_prefix + 'gas', 'BME680 Gas Sensor',
                                 gn_conn.cf_type.index('sensor'),
                                 gn_conn.cf_subt.index('number'))
    gas_dev['rrdname'] = gas_dev['name'].replace(' ', '_')[:20]
    gas_dev['proto'] = 35

    hum_dev = gn_conn.new_device(uid_prefix + 'humid', 'BME680 Humidity Sensor',
                                 gn_conn.cf_type.index('sensor'),
                                 gn_conn.cf_subt.index('humid'))
    hum_dev['rrdname'] = hum_dev['name'].replace(' ', '_')[:20]
    hum_dev['proto'] = 35

    temp_dev = gn_conn.new_device(uid_prefix + 'temp',
                                  'BME680 Temperature Sensor',
                                  gn_conn.cf_type.index('sensor'),
                                  gn_conn.cf_subt.index('temp'))
    temp_dev['rrdname'] = temp_dev['name'].replace(' ', '_')[:20]
    temp_dev['proto'] = 35

    pres_dev = gn_conn.new_device(uid_prefix + 'pres',
                                  'BME680 Pressure Sensor',
                                  gn_conn.cf_type.index('sensor'),
                                  gn_conn.cf_subt.index('pressure'))
    pres_dev['rrdname'] = pres_dev['name'].replace(' ', '_')[:20]
    pres_dev['proto'] = 35

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
    args = parse_cmdline()
    if args.debug:
        debug_mode = args.debug

    uid_prefix = args.uid_prefix + 'BME680-' + args.address + '-'

    if not os.path.isfile(args.conf):
        await initial_setup(args, uid_prefix, loop)
        exit(0)

    gn_conn = gnhast.gnhast(loop, args.conf)
    gn_conn.debug = debug_mode

    await gn_conn.gn_build_client('BME680-{0}'.format(args.address))
    gn_conn.LOG("BME680 collector starting up")

    i2c_addr = gn_conn.config['bme680coll']['i2c_addr']
    i2c_addr_int = int(i2c_addr, 16)
    sensor = init_bme680(i2c_addr_int)
    if sensor is None:
        gn_conn.LOG_ERROR('Could not intialize BME680')
        return
    burn_in = gn_conn.config['bme680coll']['burn_in']
    burn_in = 50
    poll_time = gn_conn.config['bme680coll']['update']

    # set up a signal handler
    for sig in [signal.SIGTERM, signal.SIGINT]:
        loop.add_signal_handler(sig,
                                lambda: asyncio.ensure_future(gn_conn.shutdown(sig, loop)))

    # fire up the listener and do gnhastly things..
    asyncio.ensure_future(gn_conn.gnhastd_listener())
    asyncio.ensure_future(register_devices(gn_conn))

    # burn in the sensor and then fire it up
    await burn_in_sensor(sensor, burn_in, gn_conn)
    gn_conn.LOG('Burn-in complete, starting poller')
    asyncio.ensure_future(poll_sensor(gn_conn, sensor, poll_time, uid_prefix))
    return


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main(loop))
    try:
        loop.run_forever()
    finally:
        loop.close()
    exit(0)
