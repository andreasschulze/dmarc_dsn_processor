# DMARC DSN Processor

[![markdownlint](https://github.com/andreasschulze/dmarc_dsn_processor/actions/workflows/markdownlint.yml/badge.svg)](https://github.com/andreasschulze/dmarc_dsn_processor/actions/workflows/markdownlint.yml)
[![pylint](https://github.com/andreasschulze/dmarc_dsn_processor/actions/workflows/pylint.yml/badge.svg)](https://github.com/andreasschulze/dmarc_dsn_processor/actions/workflows/pylint.yml)

Sending DMARC aggregated reports is a good thing. But if you do so, you will
note some reports are undeliverable. A simple solution is to simply ignore them.
But you do not want to deliver messages to addresses known to be undeliverable.
This may reduce you reputation.

An other option is to not generate reports once a receiver address is known to
be undeliverable. Mostly this require configuration on the report generator.

This solution follow an other approach: you still generate the reports, but
discard the messages for some days once a receiver address become known to be
undeliverable. After some days you give the receiver a new chance to have it's
problem solved.

We assume a dedicated sender address for dmarc aggregated reports. We also
assume you're using the [Postfix MTA](https://www.postfix.org) to send reports
and receive delivery status messages.

Any message **to** the address used as sender is assumed to be a delivery
status messages. Configure Postfix to deliver these messages with the
[pipe](https://www.postfix.org/pipe.8.html) delivery agent.

```txt
/etc/postfix/master.cf
  dmarc_dsn_processor unix - n n - - pipe
  flags=Rq user=nobody null_sender=
  argv=/path/to/dmarc_dsn_processor.py ${queue_id} /path/to/data_dir
```

To prevent Postfix from sending multiple recipients per delivery
request, limit parallel deliveries:

```txt
/etc/postfix/main.cf
  dmarc_dsn_processor_destination_recipient_limit = 1
```

Now add a transport map entry. You may use the inline map:

```txt
/etc/postfix/main.cf
  transport_maps = inline:{sender@example=dmarc_dsn_processor}
```

Don't forget `postfix reload` and check your logs for warning/errors.

Create the working directory:

```sh
# install -d --owner nobody /path/to/data_dir
```
