# gnhast-python-collectors
Collectors for gnhast wrtten in python

* alarmconsole - Watches for alarms, prints them to the console in color.
* bme680coll - A bme680 sensor bolted directly to the GPIO pins on a PI
* influxcoll - Read data from gnhast, feed it direcly into an influxdb
* presdiff - Super specialized.  Takes two pressure readings from devices in gnhast, and calculates the difference, and then feeds that back to gnhast as a new device.
* venstar_influx - Not a collector.  Just a tool to feed venstar runtime data into an influxdb.
* skeleton - A skeleton collector.  Basically copy this to a new directory as a starting point.

All of these require py-gnhast, and, well, a gnhast server somewhere to talk to.

see:

https://github.com/garbled1/gnhast
https://github.com/garbled1/py-gnhast
