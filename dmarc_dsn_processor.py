#!/usr/bin/env python3

"""
Andreas Schulze, 2023, https://github.com/andreasschulze

This program process dsn messages received for DMARC aggregate reports.

Usage: cat dns_message | $0 queue_id extension [data_dir]

  - extension must be present, may be empty
  - data_dir if missing, ENV[DATA_DIR] is used
  - data_dir must exist and be writeable for the current uid

the following envoronment variables are used:

  - VERBOSE
    if set with any value, the program run verbose

  - DATA_DIR
    if unset, './dmarc_dsn_processor' is used


Requirements on Debian:
apt-get install python3-minimal python3-json5 python3-validators

"""

import datetime
import email
import json
import logging
import os
import re
import sys
import validators

RE_MULTILINE     = re.compile("\n\\s+")
RE_REPORT_DOMAIN = re.compile("^.*Report Domain:\\s")
RE_SUBMITTER     = re.compile("\\sSubmitter:\\s.*$")

# [Final|Orginal]-Recipient may have a space or even not:
# Final-Resipient: rfc822; with_space@example.org
# Original-Recipient: rfc822;without_space@example.org
RE_822_PREFIX    = re.compile("rfc822;\\s?")

# report_domain in Google Groups DSN, References Header
RE_REFERENCES_REPORT_DOMAIN = re.compile("^<(.*)-\\d+@.*$")

# report_domain somewhere in the whole message
RE_BODY_REPORT_DOMAIN = re.compile("^.*Report Domain:\\s(.*)\\sSubmitter.*$", flags=re.MULTILINE)

def unfold(header_value: str):

    """
    return the header value without linebreaks
    """

    # continuation lines (intended with SPACES) are replaced
    # by exactly one SPACE
    return re.sub(RE_MULTILINE, ' ', header_value)

def get_report_domain_from_subject(subject: str):

    """
    try to extract a report domain from a Subject: header
    """

    if subject is None:
        return None

    report_domain = re.sub(RE_SUBMITTER, '',
        re.sub(RE_REPORT_DOMAIN, '', subject))

    if subject == report_domain:
        # the re above didn't catch/match
        logging.error("ERROR: unexpected subject, "
            "probably not a dsn for a dmarc report")
        save_message('no_subject_re_match')
        sys.exit(0)

    if not validators.domain(report_domain):
        # the re above did not produce a raw domainname
        logging.error("ERROR: '%s' is no valid report_domain in string, "
            "probably not a dsn for a dmarc report", report_domain)
        save_message('no_report_domain')
        sys.exit(0)

    return report_domain

def process_googlegroups_dsn(msg):

    """
    process a DSN message as seen from Google Groups
    """

    logging.debug("DEBUG: process_googlegroups_dsn")
    recipients = []

    if msg['from'] != "Mail Delivery Subsystem <mailer-daemon@googlemail.com>":
        logging.debug("DEBUG: process_googlegroups_dsn: not from googlemail.com")
        return recipients

    for header_name in 'x-failed-recipients', 'references', 'in-reply-to':
        if msg[header_name] is None:
            logging.debug("process_googlegroups_dsn: missing %s header", header_name)
            return recipients

    if msg['references'] != msg['in-reply-to']:
        logging.debug("process_googlegroups_dsn: references header != in-reply-to header")
        return recipients

    match = re.search(RE_REFERENCES_REPORT_DOMAIN, msg['references'])
    if not match:
        logging.error("ERROR: no report_domain in google groups dsn references header")
        save_message('no_report_domain_in_references_header')
        sys.exit(0)

    report_domain = match.group(1)
    if not validators.domain(report_domain):
        # the re above did not produce a raw domainname
        logging.error("ERROR: '%s' is no valid report_domain in string, "
            "probably not a dsn for a dmarc report", report_domain)
        save_message('no_report_domain')
        sys.exit(0)

    rcpt = {}
    rcpt['report_domain'] = report_domain
    rcpt['action'] = 'failed'
    rcpt['status'] = '5.1.1' # https://datatracker.ietf.org/doc/html/rfc3463#section-3.2
    rcpt['final_rcpt'] = msg['x-failed-recipients']
    rcpt["orig_rcpt"] = rcpt["final_rcpt"]

    recipients.append(rcpt)
    return recipients

def process_with_extension(extension: str, mail_data: str):

    """
    process the email, for a known extension
    in this case, only the report domain must be searched
    """

    logging.debug("DEBUG: process_with_extension")

    report_rcpt = extension.replace("=", "@")
    if not validators.email(report_rcpt):
        logging.error("ERROR: '%s' is not a valid report_rcpt", report_rcpt)
        save_message('no_report_rcpt_in_extension')
        sys.exit(0)

    match = re.search(RE_BODY_REPORT_DOMAIN, mail_data)
    if not match:
        logging.error("ERROR: no report_domain in message")
        save_message('no_report_domain_in_message')
        sys.exit(0)

    report_domain = match.group(1)
    if not validators.domain(report_domain):
        # the re above did not produce a raw domainname
        logging.error("ERROR: '%s' is no valid report_domain in string,"
            "probably not a dsn for a dmarc report", report_domain)
        save_message('no_report_domain')
        sys.exit(0)

    rcpt = {}
    rcpt['report_domain'] = report_domain
    rcpt["action"] = "any_reason"
    rcpt["orig_rcpt"] = extension.replace("=", "@")
    rcpt["date"] = DATE

    recipients = []
    recipients.append(rcpt)
    return recipients

# pylint: disable=too-many-branches
def process_dsn(mail_data: str):

    """
    process the email, extract dsn data
    """

    msg = email.message_from_string(mail_data)
    recipients = []
    orig_subject = None
    report_domain = None

    for part in msg.walk():
        if part.get_content_type() == "message/delivery-status":
            for subpart in part.walk():
                rcpt = {}
                # https://datatracker.ietf.org/doc/html/rfc3461#section-6.3
                if 'Action' in subpart and 'Final-Recipient' in subpart:
                    rcpt["action"] = subpart['Action']
                    if rcpt["action"] == 'delayed':
                        logging.info('INFO: this is only about a delayed delivery')
                        sys.exit(0)

                    rcpt["final_rcpt"] = re.sub(RE_822_PREFIX, '', subpart['Final-Recipient'])
                    if 'Original-Recipient' in subpart:
                        rcpt["orig_rcpt"] = re.sub(RE_822_PREFIX, '', subpart['Original-Recipient'])
                    else:
                        rcpt["orig_rcpt"] = rcpt["final_rcpt"]

                    rcpt["diag_code"] = None
                    if 'Diagnostic-Code' in subpart:
                        # may be multiline
                        rcpt["diag_code"] = unfold(subpart['Diagnostic-Code'])

                    rcpt["status"] = None
                    if 'Status' in subpart:
                        rcpt["status"] = subpart['Status']

                    logging.debug("DEBUG: adding final_rpct=%s, orig_rcpt=%s",
                                  rcpt["final_rcpt"], rcpt["orig_rcpt"])
                    recipients.append(rcpt)

        if part.get_content_type() == "message/rfc822":
            for subpart in part.walk():
                if orig_subject is None and subpart["Subject"] is not None:
                    orig_subject = unfold(subpart["Subject"])
                    logging.debug("DEBUG: orig_subject=%s", orig_subject)

        if part.get_content_type() == "text/rfc822-headers":
            payload = email.message_from_string(part.get_payload())
            if orig_subject is None and payload["Subject"] is not None:
                orig_subject = unfold(payload["Subject"])
                logging.debug("DEBUG: orig_subject=%s", orig_subject)

    report_domain = get_report_domain_from_subject(orig_subject)

    # so far no results?
    if not recipients:
        recipients = process_googlegroups_dsn(msg)

    for rcpt in recipients:
        if "report_domain" not in rcpt:
            logging.debug("DEBUG: rcpt=%s, adding report_domain='%s'",
                rcpt['orig_rcpt'], report_domain)
            rcpt["report_domain"] = report_domain
        rcpt["date"] = DATE

    return recipients

def dsn_detail_to_data_dir(dsn_detail: dict, data_dir: str):

    """
    append dsn_details to a file in data_dir
    """

    for dsn in dsn_detail:
        report_domain = dsn['report_domain']
        if report_domain is not None:
            logging.info("INFO: saving dsn_details for domain '%s'", report_domain)
            filename = data_dir + '/domains/' + report_domain
            with open(filename, 'a', encoding="utf-8") as file:
                file.write(json.dumps(dsn) + "\n")
        else:
            logging.error("ERROR: no report_domain in '%s'", dsn)
            save_message('no_report_domain')

def save_message(reason: str):

    """
    save MAIL_DATA for debugging purposes
    """

    pathname = DATA_DIR + '/saved/' + QUEUE_ID + '.' + reason
    with open(pathname, 'a', encoding='utf-8') as file:
        file.write(MAIL_DATA)
        file.close()
        logging.debug("DEBUG: messages saved to '%s'", pathname)

# main

# first: slurp the message so it could be saved in case of some errors
MAIL_DATA = ""
for line in sys.stdin:
    # pylint: disable=consider-using-join
    MAIL_DATA += line

LOG_LEVEL = logging.INFO
if os.getenv('VERBOSE'):
    LOG_LEVEL = logging.DEBUG
logging.basicConfig(format='%(message)s', level=LOG_LEVEL)

# argv[0] = program name
# argv[1] = queue_id
# argv[2] = extension
# argv[3] = data_dir, optional, default to $DATA_DIR, default to ./dmarc_dsn_processor
# len(argv) == 4

if len(sys.argv) < 3:
    logging.error("ERROR: usage: $0 queue_id extension [work_dir]")
    sys.exit(1)

QUEUE_ID  = sys.argv[1]
EXTENSION = sys.argv[2]

if len(sys.argv) > 2 and sys.argv[3] is not None:
    DATA_DIR = sys.argv[3]
else:
    DATA_DIR = os.getenv('DATA_DIR', './dmarc_dsn_processor')

if os.path.isdir(DATA_DIR):
    logging.debug('DEBUG: using %s', DATA_DIR)
else:
    logging.error('ERROR: %s do not exist or is not a directory', DATA_DIR)
    sys.exit(1)

if not os.access(DATA_DIR, os.W_OK):
    logging.error('ERROR: %s must be writable', DATA_DIR)
    sys.exit(1)

# create subdirs
for subdir in [ 'domains', 'saved']:
    try:
        os.mkdir(DATA_DIR + '/' + subdir + '/')
    except FileExistsError:
        # ignore if subdir already exist
        pass

# now we may call 'save_message' ...

today = datetime.date.today()
DATE = today.strftime("%Y%m%d")

if EXTENSION != "":
    logging.debug("DEBUG: extension='%s'", EXTENSION)
    dsn_details = process_with_extension(EXTENSION, MAIL_DATA)
else:
    dsn_details = process_dsn(MAIL_DATA)

logging.debug("DEBUG: dsn_details='%s'", dsn_details)
if not dsn_details:
    logging.debug("DEBUG: dsn_details is empty")
    save_message('no_dsn_details')
    sys.exit(0)

logging.debug("DEBUG: dsn_details found")
dsn_detail_to_data_dir(dsn_details, DATA_DIR)
sys.exit(0)
