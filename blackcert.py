#!/usr/bin/env python3

import configparser
import logging
import os
import sys
import time
import certstream
import argparse
import json
import datetime
import requests
from pathlib import Path


VERSION = '1'


def setup_logging(LOG_PATH,LOG_LEVEL):
    """Creates a shared logging object for the application"""
    # create logging object
    logger = logging.getLogger('blackcert')
    logger.setLevel(LOG_LEVEL)
    # create a file and console handler
    fh = logging.FileHandler(LOG_PATH)
    fh.setLevel(LOG_LEVEL)
    ch = logging.StreamHandler()
    ch.setLevel(LOG_LEVEL)
    # create a logging format
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def parse_configs(CONFIG_PATH):
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH)
    settings = {}

    for section in config.sections():
        for key in config[section]:
            try:
                settings[key] = perform_lookup(key, config.get(section, key))
            except Exception as e:
                print("ERROR - with configuration file at {0} failed with error {1}".format(CONFIG_PATH, e))
                sys.exit(1)
    return settings


def perform_lookup(config_key, config_value):
    if config_key == 'keywords':
        keywords = [e.strip() for e in config_value.split(',')]
        return keywords
    else:
        return config_value


def process_message(domain, message):
    result = {}
    result['timestamp'] = str(datetime.datetime.utcnow().isoformat())
    result['serial'] = message['data']['leaf_cert']['serial_number']
    result['domain'] = domain
    result['subject'] = message['data']['leaf_cert']['subject']['aggregated']
    result['CA'] = [c['subject']['CN'] for c in message['data']['chain']]
    result['CA_serials'] = [c['serial_number'] for c in message['data']['chain']]
    return result


def sendslack(slackhook, domain, result):
    """Send message to Slack"""

    slack_data = {"attachments": [{
        "fallback": ":lock: certificate changes have been detected for: {0}\
                                        \n```{1}```\n".format(str(domain), json.dumps(result, indent=2)),
        "color": "#7236a6",
        "author_name": "blackcert",
        "author_link": "https://github.com/d1vious/blackcert",
        "title": ":lock: certificate changes have been detected for {0}".format(str(domain)),
        "mrkdwn_in": ["text", "title", "pretext", "fields"],
        "fields": [
            {
                "title": "cert material",
                "value": "```{0}```".format(json.dumps(result, indent=2)),
                "short": False
            }
        ]
    }]}

    response = requests.post(
        slackhook, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'}
    )

    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text))

def write_results(result):
    try:
        with open(OUTPUT_PATH, 'a') as outfile:
            json.dump(result, outfile)
    except Exection as e:
        log.error("writing result file: {0}".format(str(e)))


def callback(message, context):
    #log.info("Message -> {}".format(message))
    keywords = config['keywords']
    if message['message_type'] == "heartbeat":
        return

    if message['message_type'] == "certificate_update":
        all_domains = message['data']['leaf_cert']['all_domains']
        
        for domain in all_domains:
            for keyword in keywords:
                if domain.find(keyword) != -1:
                    log.info("matched domain: {0} for keyword: {1}".format(domain, keyword))
                    result = process_message(domain, message)
                    # print(json.dumps(result, indent=2))
                    sendslack(config['hook'], domain, result)
                    write_results(result)

def on_open(instance):
    # Instance is the CertStreamClient instance that was opened
    print("Connection successfully established!")

def on_error(instance, exception):
    # Instance is the CertStreamClient instance that barfed
    print("Exception in CertStreamClient! -> {}".format(exception))


if __name__ == "__main__":
    # grab arguments
    parser = argparse.ArgumentParser(description="starts listening for newly registered certificates and sends slack alerts when it matches")
    parser.add_argument("-c", "--config", required=False, default="config.ini",
                        help="path to the configuration file of blackcert")
    parser.add_argument("-o", "--output", required=False, default="results.log",
                        help="path to a JSON log file of the matches")
    parser.add_argument("-v", "--version", default=False, action="store_true", required=False,
                        help="shows current blackcert version")

    # parse them
    args = parser.parse_args()
    ARG_VERSION = args.version
    config = args.config
    OUTPUT_PATH = args.output

    print("""
_     _            _                 _   
| |   | |          | |               | |  
| |__ | | __ _  ___| | _____ ___ _ __| |_ 
| '_ \| |/ _` |/ __| |/ / __/ _ \ '__| __|
| |_) | | (_| | (__|   < (_|  __/ |  | |_ 
|_.__/|_|\__,_|\___|_|\_\___\___|_|   \__|                           
    """)

    # parse config
    blackcert_config = Path(config)
    if blackcert_config.is_file():
        print("blackcert {1} is using config at path {0}".format(blackcert_config, str(VERSION)))
        configpath = str(blackcert_config)
    else:
        print("ERROR: blackcert failed to find a config file at {0} or {1}..exiting".format(blackcert_config))
        sys.exit(1)

    # Parse config
    config = parse_configs(configpath)
    log = setup_logging(config['log_path'], 'INFO')

    if ARG_VERSION:
        log.info("version: {0}".format(VERSION))
        sys.exit(0)
    log.info("alerting to keywords: {0}".format(config['keywords']))
    # certstream.listen_for_events(callback, on_open=on_open, on_error=on_error, url=config['certstream_url'])
    certstream.listen_for_events(callback, url=config['certstream_url'])
