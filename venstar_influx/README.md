# Venstar influx feeder #

Not really a collector. If you happen to have a venstar, and you happen
to run influxdb for grafana, this will allow you to push the history
of runtimes (of which it keeps like bajillion) to the db.

The full history is quite large.  When you run the collector, it pulls down
the full 117k or so, and then feeds it into influx.  If you want to do this
in a nightly cronjob, this is non-ideal.  There is a --max_days argument to
handle this. It will still pull the full feed from the venstar (no option),
but it will only push the last N days into influx.  Because it reads the
current day, it will also push that, so you should call it with +1 day to the
period you run the command.  For example, in a nightly cron, run it with
--max_days 2.

The notify mode takes 65 seconds to run, but is better if you have a DHCP
addressed venstar and no ddns. If you have a static, or ddns'ed one, then
user the -u option instead.

The notify mode requires gnhast to be installed, because it uses the
notify_listen command which does an SSDP scan.  (you should run one just for
fun, it's amazing how many devices babble onto the network when you hit them
with an SSDP)

