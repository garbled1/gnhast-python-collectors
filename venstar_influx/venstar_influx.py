#!/usr/bin/env python3

import time
import argparse
from influxdb import InfluxDBClient
import datetime
import json
import subprocess
import urllib.request


def parse_cmdline():
    parser = argparse.ArgumentParser(description='Venstar Stats Tool')
    parser.add_argument('-v', '--venstar_name', type=str, action='store',
                        help='Name of venstar unit')
    parser.add_argument('-f', '--file', type=str, action='store',
                        default=None,
                        help='json data file to load, sets debug mode')
    parser.add_argument('-u', '--venstar_url', type=str, action='store',
                        default=None,
                        help='URL of venstar, ex http://192.168.1.5/')
    parser.add_argument('-i', '--influx_host', type=str, action='store',
                        default='127.0.0.1',
                        help='hostname of influx db (127.0.0.1)')
    parser.add_argument('-p', '--influx_port', type=int, action='store',
                        default=8086,
                        help='port number of influx db (8086)')
    parser.add_argument('--influx_user', type=str, action='store',
                        default=None,
                        help='InfluxDB username')
    parser.add_argument('--influx_pass', type=str, action='store',
                        default=None,
                        help='InfluxDB password')
    parser.add_argument('-d', '--influx_db', type=str, action='store',
                        default='gnhast',
                        help='InfluxDB database name (default: gnhast)')
    parser.add_argument('-m', '--max_days', type=int, action='store',
                        default=99999999,
                        help='Maximum number of days to look back in the data')
    parser.add_argument('-D', '--dry_run', action='store_true',
                        default=False,
                        help='Dry-Run, no datapoints will be written')

    args = parser.parse_args()
    return args


def run_notify(venstar_name):
    notify_cmd = "notify_listen -t 65 2> /dev/null | grep -B 1 name:" + venstar_name + ": | grep ^Location | sort -u | awk '{print $2}' | tr -d '\r'"

    notify_url = ''
    i = 0

    while notify_url is '' and i < 5:
        result = subprocess.run(notify_cmd, stdout=subprocess.PIPE, shell=True)
        r_url = result.stdout.decode("utf-8")
        notify_url = r_url.rstrip()
        i += 1

    print("Notify returned url after {1} tries: {0}".format(notify_url, i))
    return(notify_url)


def parse_json(json_data, max_days):
    now_sec = int(time.time())

    json_body = []
    for dp in json_data['runtimes']:
        # skip last element
        if dp == json_data['runtimes'][-1]:
            continue
        fields = {i: dp[i] for i in dp if i != 'ts'}
        point = {
            "measurement": "venstar_runtime",
            "time": dp['ts'],
            "fields": fields
        }
        if dp['ts'] > (now_sec - max_days * 86400):
            json_body.append(point)
    return(json_body)


def main():
    args = parse_cmdline()

    try:
        if args.influx_user and args.influx_pass:
            db_client = InfluxDBClient(host=args.influx_host,
                                       port=args.influx_port,
                                       username=args.influx_user,
                                       password=args.influx_pass)
        else:
            db_client = InfluxDBClient(host=args.influx_host,
                                       port=args.influx_port)
    except:
        print("Cannot connect to InfluxDB!")
        exit(1)

    try:
        db_client.switch_database(args.influx_db)
    except:
        print("Cannot find db named {0}, please create".format(args.influx_db))
        exit(1)

    if args.file is not None:
        if args.venstar_name is None:
            venstar_name = 'MainSouth'
        else:
            venstar_name = args.venstar_name
        json_file = open(args.file)
        json_data = json.load(json_file)
        json_body = parse_json(json_data, args.max_days)
        tags = {"name": venstar_name}
        if not args.dry_run:
            db_client.write_points(json_body, tags=tags, time_precision='s')

        exit(0)

    if args.venstar_url is None:
        if args.venstar_name is None:
            print("ERROR: Need either venstar URL or name")
            exit(1)
        print("INFO: Running nofity, takes 65 seconds")
        venstar_url = run_notify(args.venstar_name)
    else:
        venstar_url = args.venstar_url

    if args.venstar_name is None:
        print("Asking venstar for it's name")
        ven_info = venstar_url + '/query/info'
        try:
            info_d = urllib.request.urlopen(ven_info, timeout=10)
        except Exception as e:
            print("Cannot contact venstar for info: {0}".format(str(e)))
            exit(1)
        data = info_d.read()
        encoding = info_d.info().get_content_charset('utf-8')
        info_json = json.loads(data.decode(encoding))
        info_d.close()
        venstar_name = info_json['name']
        print("name: {0}".format(venstar_name))
        # don't stammer the poor thing
        time.sleep(5)
    else:
        venstar_name = args.venstar_name

    ven_runtimes = venstar_url + '/query/runtimes'
    print("Asking {0} for runtime data".format(venstar_name))
    try:
        run_d = urllib.request.urlopen(ven_runtimes, timeout=240)
        data = run_d.read()
        encoding = run_d.info().get_content_charset('utf-8')
        runtime_data = json.loads(data.decode(encoding))
        print("Venstar gave us {0} results".format(str(len(runtime_data['runtimes']))))
        run_d.close()
    except Exception as e:
        print("Cannot contact venstar for runtime: {0}".format(str(e)))
        exit(1)

    json_body = parse_json(runtime_data, args.max_days)
    tags = {"name": venstar_name}
    if args.dry_run:
        print("Would send to influx:")
        print(json.dumps(json_body, indent=2))
        print("Tags:")
        print(tags)
    else:
        try:
            db_client.write_points(json_body, tags=tags, time_precision='s')
        except Exception as e:
            print("Cannot contact influx: {0}".format(str(e)))
    exit(0)

main()
