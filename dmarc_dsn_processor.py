#!/usr/bin/env python3

"""
Andreas Schulze, 2023, https://github.com/andreasschulze

This program process dsn messages received for DMARC aggregate reports.

Usage: cat dns_message | $0 queue_id [data_dir]

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

# pylint: disable=too-many-branches
def process_dsn(mail_data: str):

    """
    process the email, extract dsn data
    """

    msg = email.message_from_string(mail_data)
    recipients = []
    orig_subject = None
    report_domain = None
    re_multiline = re.compile("\n\\s+")
    re_report_domain = re.compile("^Report Domain:\\s")
    re_submitter = re.compile("\\sSubmitter:\\s.*$")
    for part in msg.walk():
        if part.get_content_type() == "message/delivery-status":
            for subpart in part.walk():
                rcpt = {}
                if 'Action' in subpart and 'Original-Recipient' in subpart:
                    rcpt["action"] = subpart['Action']
                    rcpt["orig_rcpt"] = subpart['Original-Recipient'].replace('rfc822;', '')
                    rcpt["diag_code"] = None
                    if 'Diagnostic-Code' in subpart:
                        # kann aus mehreren Zeilen bestehen
                        # mit SPACE eingerückte Folgezeilen werden nur durch ein SPACE ersetzt
                        rcpt["diag_code"] = re.sub(re_multiline, ' ', subpart['Diagnostic-Code'])
                    rcpt["status"] = None
                    if 'Status' in subpart:
                        rcpt["status"] = subpart['Status']
                    logging.debug("DEBUG: adding rpct=%s", rcpt["orig_rcpt"])
                    recipients.append(rcpt)

        if part.get_content_type() == "message/rfc822":
            for subpart in part.walk():
                if orig_subject is None and subpart["Subject"] is not None:
                    orig_subject = subpart["Subject"]
                    logging.debug("DEBUG: orig_subject=%s", orig_subject)

    if orig_subject is not None:
        report_domain = re.sub(re_submitter, '',
          re.sub(re_report_domain, '', orig_subject))

        if orig_subject == report_domain:
            # the re above didn't catch/match
            logging.error("ERROR: unexpected subject, probably not a dsn for a dmarc report")
            save_message('no_subject_re_match')
            sys.exit(0)

        if not validators.domain(report_domain):
            # the re above did not produce a raw domainname
            logging.error("ERROR: unexpected subject, probably not a dsn for a dmarc report")
            save_message('no_subject_domainname')
            sys.exit(0)

    for rcpt in recipients:
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
# argv[2] = first parameter (data_dir), optional, default './dmarc_dsn_processor
# len(argv) == 3

if len(sys.argv) < 2:
    logging.error("ERROR: usage: $0 queue_id [work_dir]")
    sys.exit(1)

QUEUE_ID = sys.argv[1]

if len(sys.argv) > 2 and sys.argv[2] is not None:
    DATA_DIR = sys.argv[2]
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
        # ignore if it already exist
        pass

# now we could call 'save_message' ...

today = datetime.date.today()
DATE = today.strftime("%Y%m%d")

dsn_details = process_dsn(MAIL_DATA)
logging.debug("DEBUG: dsn_details='%s'", dsn_details)
if not dsn_details:
    logging.debug("DEBUG: dsn_details is empty")
    save_message('no_dsn_details')
    sys.exit(0)

logging.debug("DEBUG: dsn_details is not empty")
dsn_detail_to_data_dir(dsn_details, DATA_DIR)
sys.exit(0)
