#! /usr/bin/env python3

"""
create a postfix discard table from data_dir

usage: /path/to/$0

"""

import datetime
import json
import logging
import os
import sys

def handle_dsn(filename: str):

    """
    add orig_rcpt to discard list
    """
    with open(filename, 'r', encoding='utf-8') as json_file:
        line = None
        for line in json_file:
            # skip all lines
            pass
        # 'line' is now the last line ...
        dsn_data = json.loads(line)

        date = dsn_data['date']
        orig_rcpt = dsn_data['orig_rcpt']

        if date is None:
            date = 'unknown'

        logging.debug("DEBUG: orig_rcpt=%s, domain=%s, date=%s", orig_rcpt, filename, date)
        map_line = f"{orig_rcpt} discard:report for {file} bounced {date} last time"
        print(map_line)

# main

LOG_LEVEL = logging.INFO
if os.getenv('VERBOSE'):
    LOG_LEVEL = logging.DEBUG
logging.basicConfig(format='%(message)s', level=LOG_LEVEL)

# same 6 lines of code in dmarc_dsn_processor.py ...
# pylint: disable=duplicate-code
DATA_DIR = os.getenv('DATA_DIR', './dmarc_dsn_processor')
if os.path.isdir(DATA_DIR):
    logging.debug('DEBUG: using %s', DATA_DIR)
else:
    logging.error('ERROR: %s do not exist or is not a directory', DATA_DIR)
    sys.exit(1)

if not os.path.exists(DATA_DIR + '/domains/'):
    logging.error('ERROR: %s/domains do not exist, check DATA_DIR', DATA_DIR)
    sys.exit(1)

MIN_AGE_IS_INT = True
MIN_AGE = os.getenv('MIN_AGE', '30')
try:
    int(MIN_AGE)
except ValueError:
    MIN_AGE_IS_INT = False

if MIN_AGE_IS_INT:
    MIN_AGE = int(MIN_AGE)
else:
    logging.error("ERROR: ENV[MIN_AGE] = '%s', but must be an integer", MIN_AGE)
    sys.exit(1)

# don't accept nagative ages
if MIN_AGE < 0:
    logging.error("ERROR: ENV[MIN_AGE] must be a positive integer")
    sys.exit(1)

# give the reciever a real chance to fix it's issue
if MIN_AGE > 90:
    logging.error("ERROR: ENV[MIN_AGE] must be max. 90")
    sys.exit(1)

TODAY = datetime.datetime.today()

os.chdir(DATA_DIR + '/domains/')
for file in os.listdir('.'):
    if os.path.isfile(file):
        file_mod_time = datetime.datetime.fromtimestamp(os.path.getmtime(file))
        age = TODAY - file_mod_time

        if age.days < MIN_AGE:
            handle_dsn(file)
        else:
            logging.debug("DEBUG: file %s is older then %s day(s)", file, MIN_AGE)
