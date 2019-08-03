# influxcoll

A simple collector to connect to a gnhast server, pull all data from all
devices, and feed it into an influxdb.

Requires python 3.5 or higher

## How to use ##

The conf file defaults to /usr/local/etc/influxcoll.conf.  The first time
you run the collector, it will try to connect to a gnhastd instance on
localhost, and an influxdb on localhost.  Once it does so, it will create
a config file for you, and a database called "gnhast" in the influxdb.

You can change these initial options on the commandline:

usage: influxcoll.py [-h] [-c CONF] [-d] [-m] [--server SERVER] [--port PORT]
                     [--influxdb_name INFLUXDB_NAME]
                     [--influxdb_host INFLUXDB_HOST]
                     [--influxdb_port INFLUXDB_PORT]
                     [--influxdb_user INFLUXDB_USER]
                     [--influxdb_pass INFLUXDB_PASS]
InfluxDB Collector

optional arguments:
  -h, --help            show this help message and exit
  -c CONF, --conf CONF  Path to config file
  -d, --debug           Debug mode
  -m, --dumpconf        Write out a config file and exit
  --server SERVER       Hostname of gnhastd server
  --port PORT           Port gnhastd listens on
  --influxdb_name INFLUXDB_NAME
                        Influx database name
  --influxdb_host INFLUXDB_HOST
                        InfluxDB host
  --influxdb_port INFLUXDB_PORT
                        InfluxDB port #
  --influxdb_user INFLUXDB_USER
                        InfluxDB user name
  --influxdb_pass INFLUXDB_PASS
                        InfluxDB user password

## The conf file ##

You can now edit the conf file if you wish.  Important values:

feed:  If set to 0, only update influx on change of device.  If set to
a positive integer, update influx every feed seconds.

recheck: Defaults to 3600.  Recheck gnhast for new devices every X seconds.

