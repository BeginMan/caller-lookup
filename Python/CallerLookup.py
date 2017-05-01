#!/usr/bin/python
#
# Usage:    CallerLookup.py [-h] --number PHONE_NUMBERS [PHONE_NUMBERS ...]
#                       [--region DEFAULT_REGION] [--path APPLICATION_PATH]
#                       [--settings SETTING_PATH] [--cookies COOKIES_PATH]
#                       [--countrycodes COUNTRY_DATA_PATH] [--logpath LOG_PATH]
#                       [--username USERNAME] [--password PASSWORD]
#                       [--otpsecret OTPSECRET] [--debug]
#
#           Reverse Caller Id
#
#           optional arguments:
#             -h, --help            show this help message and exit
#             --number PHONE_NUMBERS [PHONE_NUMBERS ...], --n PHONE_NUMBERS [PHONE_NUMBERS ...]
#                                   Phone number accepted in any standard format. When not
#                                   in international format, the default region parameter
#                                   must be supplied
#             --region DEFAULT_REGION, --r DEFAULT_REGION
#                                   The home region that the trunk belongs to. Only
#                                   required when phone number is supplied without an
#                                   international dialling code. Must be in CCN format.
#                                   SeeCountryCodes.json
#             --path APPLICATION_PATH, --p APPLICATION_PATH
#                                   Working Directory
#             --settings SETTING_PATH, --s SETTING_PATH
#                                   Path to Settings INI file
#             --cookies COOKIES_PATH, --c COOKIES_PATH
#                                   Path to Cookie store file
#             --countrycodes COUNTRY_DATA_PATH, --cc COUNTRY_DATA_PATH
#                                   Path to Country Codes data file
#             --logpath LOG_PATH, --l LOG_PATH
#                                   Path to Log Directory
#             --username USERNAME, --un USERNAME
#                                   Google Account Username
#             --password PASSWORD, --pw PASSWORD
#                                   Google Account Password
#             --otpsecret OTPSECRET, --otp OTPSECRET
#                                   Google Account Two-Factor Auth Secret
#             --debug               Debug mode
#
#           Example: CallerLookup.py --number +12024561111
#                    CallerLookup.py --number 02079309000 --region gb
#
# Author:       Scott Philip (sp@scottphilip.com)
# Source:       https://github.com/scottphilip/caller-lookup/
# Licence:      GNU GENERAL PUBLIC LICENSE (Version 3, 29 June 2007)
#               CallerLookup Copyright (C) 2017 SCOTT PHILIP
#               This program comes with ABSOLUTELY NO WARRANTY
#               This is free software, and you are welcome to redistribute it
#               under certain conditions
#               https://github.com/scottphilip/caller-lookup/blob/master/LICENSE.md
#
import sys
assert sys.version_info >= (2, 7)

import StringIO
import argparse
import configparser
import datetime
import gzip
import http.cookiejar
import json
import logging
import os
import time
import phonenumbers
import requests.cookies
from future.standard_library import install_aliases

install_aliases()
# noinspection PyUnresolvedReferences
from urllib.parse import urlparse, urlencode
# noinspection PyUnresolvedReferences
from urllib.request import urlopen, Request, HTTPErrorProcessor
# noinspection PyUnresolvedReferences
from urllib.error import HTTPError
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait


class CallerLookup(object):

    class CallerLookupParams(object):

        setting_path = "/var/lib/CallerLookup/CallerLookup.ini"
        cookies_path = "/var/lib/CallerLookup/CallerLookup.cookies"
        country_data_path = "/var/lib/CallerLookup/CountryCodes.json"
        log_path = "/var/lib/CallerLookup/CallerLookup.log"
        is_debug = False
        username = None
        password = None
        otpsecret = None

        def __init__(self, dict_values=None):
            if not dict_values is None:
                for key in dict_values:
                    if not dict_values[key] is None:
                        setattr(self, key, dict_values[key])

        def set_root_path(self, path):
            import ntpath
            self.setting_path = os.path.join(path, ntpath.basename(self.setting_path))
            self.cookies_path = os.path.join(path, ntpath.basename(self.cookies_path))
            self.country_data_path = os.path.join(path, ntpath.basename(self.country_data_path))
            self.log_path = os.path.join(path, ntpath.basename(self.log_path))

    class CallerLookupConstants(object):

        USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Ubuntu " \
                     "Chromium/33.0.1750.152 Chrome/33.0.1750.152 Safari/537.36"
        DEFAULT_HEADERS = {"Accept": "application/json, text/plain, */*",
                           "Accept-Language": "en-US",
                           "Accept-Encoding": "gzip",
                           "Connection": "Keep-Alive",
                           "User-Agent": USER_AGENT}
        URL_SEARCH = "https://www.truecaller.com/api/search?{0}"
        URL_TOKEN = "https://www.truecaller.com/api/auth/google?clientId=4"
        URL_TOKEN_CALLBACK = "https://www.truecaller.com/auth/google/callback"
        URL_GOOGLE_ACCOUNTS = "https://accounts.google.com"
        URL_GOOGLE_MYACCOUNT = "https://myaccount.google.com"
        URL_GOOGLE_ACCOUNTS_SERVICELOGIN = "{0}/ServiceLogin".format(URL_GOOGLE_ACCOUNTS)
        URL_GOOGLE_ACCOUNTS_NOFORM = "{0}/x".format(URL_GOOGLE_ACCOUNTS)

    class OAuth(object):

        PROTOCOL = "https"
        DOMAIN = "accounts.google.com"
        PATH = "/o/oauth2/v2/auth"
        DATA = {"response_type": "token",
                "client_id": "1051333251514-p0jdvav4228ebsu820jd3l3cqc7off2g.apps.googleusercontent.com",
                "redirect_uri": "https://www.truecaller.com/auth/google/callback",
                "scope": "https://www.googleapis.com/auth/userinfo.email "
                         "https://www.googleapis.com/auth/userinfo.profile "
                         "https://www.google.com/m8/feeds/"}

    def __init__(self, caller_lookup_parameters=None, dict_parameters=None):

        if caller_lookup_parameters is None:
            caller_lookup_parameters = CallerLookup.CallerLookupParams(dict_parameters)
        self.settings = caller_lookup_parameters

        global log_helper
        if log_helper is None:
            log_helper = self.LogHelper(self.settings)

        log_helper.debug("#############################################################################")
        # log_helper.debug("{0:20} {1}".format("ARGS", str(settings)))

        self._generator = CallerLookup.TokenGenerator(self.settings)

    def search(self, phone_number, default_region):
        start = time.time()
        result = self._search(phone_number, default_region)
        elapsed = time.time() - start
        if self.settings.is_debug:
            result["time_taken"] = str(elapsed)
        return result

    def _search(self, phone_number, default_region):

        def format_phone_number(format_number, format_region):
            format_valid = False
            try:
                phone_number = phonenumbers.parse(format_number, format_region.upper())
                format_region = get_phone_number_region(str(phone_number.country_code), format_region).upper()
                format_number = phonenumbers.format_number(phone_number, phonenumbers.PhoneNumberFormat.E164)
                format_valid = phonenumbers.is_valid_number(phone_number)
            except:
                ignore = True
            return format_valid, format_number, format_region

        def get_phone_number_region(country_dial_code, provided_region):
            try:
                country_data = json.loads(open(self.settings.country_data_path).read())
                for country in country_data:
                    if country["CC"] == country_dial_code:
                        return country["CCN"]
            except Exception as e:
                log_helper.error("{0:20} Error Loading Country Code Data: {1}".format("COUNTRY DATA", str(e)))
            return provided_region

        def get_response_invalid(number, region):
            return {"result": "invalid_number",
                    "number": number,
                    "region": region}

        def get_response_error(message):
            return {"result": "error",
                    "message": message}

        try:

            (is_valid_number, phone_number, default_region) = \
                format_phone_number(phone_number, default_region)
            if not is_valid_number:
                log_helper.info("{0:20s} {1:30s} {2} ({3})".format("SEARCH",
                                                                   "Invalid Number",
                                                                   phone_number,
                                                                   default_region))
                return get_response_invalid(phone_number, default_region)

            log_helper.info("{0:20s} {1:30s} {2} ({3})".format("SEARCH",
                                                               "PARAMETERS",
                                                               phone_number,
                                                               default_region))

            with CallerLookup.HttpHandler(self.settings) as handler:
                query = CallerLookup.CallerLookupConstants.URL_SEARCH.format(urlencode({"type": 4,
                                                                   "countryCode": default_region,
                                                                   "q": phone_number}))
                fail_count = 0
                while fail_count <= 1:
                    ignore_cache = fail_count > 0
                    token = self._generator.token(handler, ignore_cache)
                    if token is None:
                        fail_count += 1
                        continue
                    (token_res_code, token_res_data, token_res_header) = handler.http_get(query, [
                        ("Authorization", "Bearer {0}".format(token)),
                        ("Host", "www.truecaller.com"),
                        ("Referer", "https://www.truecaller.com/")])
                    if token_res_code == 200:
                        return self._format_data(token_res_data, phone_number, default_region)
                    elif token_res_code == 401:
                        log_helper.info("Token {0} has expired.".format(token))
                    else:
                        log_helper.info(
                            "Token {0} resulted in status code: {1} {2} ".format(token, token_res_code, token_res_data))
                    fail_count += 1

                raise Exception("Failed {0} times attempting query {1}".format(fail_count, query))

        except Exception as ex:
            log_helper.error(str(ex))
            raise

    def _format_data(self, result_data, phone_number, default_region):
        result = {"result": "unknown",
                  "number": phone_number,
                  "region": default_region}
        data = json.loads(result_data)
        if "data" in data:
            data = data["data"]
        if len(data) > 0:
            data = data[0]
        if "score" in data:
            result["score"] = data["score"]
        if "addresses" in data:
            addresses = data["addresses"]
            if len(addresses) > 0:
                if "countryCode" in addresses[0]:
                    result["region"] = addresses[0]["countryCode"].upper()
                if "address" in addresses[0]:
                    result["address"] = addresses[0]["address"]
        if "phones" in data:
            phones = data["phones"]
            if len(phones) > 0:
                if "e164Format" in phones[0]:
                    result["number_e164"] = phones[0]["e164Format"]
                if "nationalFormat" in phones[0]:
                    result["number_national"] = phones[0]["nationalFormat"]
                if "dialingCode" in phones[0]:
                    result["region_dial_code"] = phones[0]["dialingCode"]

        if "name" in data:
            result["name"] = data["name"]
            result["result"] = "success"
            log_helper.info("{0:20s} {1:30s} {2}".format("SEARCH",
                                                         "RESULT",
                                                         str(result)))
            return result
        return result

    class TokenGenerator(object):

        def __init__(self, settings):

            self.settings = settings
            self.load_credentials()

        def load_credentials(self):
            if self.settings.username is None:
                self.settings.username = CallerLookup.SettingHelper \
                    .get_setting(self.settings.setting_path, "Credentials", "username")
                self.settings.password = CallerLookup.SettingHelper \
                    .get_setting(self.settings.setting_path, "Credentials", "password")
                self.settings.otpsecret = CallerLookup.SettingHelper \
                    .get_setting(self.settings.setting_path, "Credentials", "otpsecret")

        def token(self, handler, ignore_cache=False):
            if not ignore_cache:
                cache_date = CallerLookup.SettingHelper.get_setting(self.settings.setting_path, "Cache", "TokenExpiry")
                if cache_date is not None and datetime.datetime.strptime(cache_date, "%Y-%m-%d %H:%M:%S") \
                        > datetime.datetime.now():
                    token = CallerLookup.SettingHelper.get_setting(self.settings.setting_path, "Cache", "Token")
                    log_helper.debug("Cached Token: " + token)
                    return token
            return self._get_new_token(handler)

        def _get_new_token(self, handler):

            def _get_token_url():
                return "{0}://{1}{2}?{3}" \
                    .format(CallerLookup.OAuth.PROTOCOL,
                            CallerLookup.OAuth.DOMAIN,
                            CallerLookup.OAuth.PATH,
                            urlencode(CallerLookup.OAuth.DATA))

            def _get_refreshed_token():
                url = _get_token_url()
                if not handler.is_cookie_available(url):
                    return None
                (oauth_res_code, oauth_res_data, oauth_res_header) = handler.http_get(url)
                if oauth_res_code != 302 or not "location" in oauth_res_header:
                    return None
                redirect_location = oauth_res_header["location"]
                log_helper.debug("{0:20} {1:30} {2}".format("REFRESH TOKEN", "Redirect Url", redirect_location))
                if redirect_location.count(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS) > 0:
                    return None
                if redirect_location.count("#") == 0:
                    return None
                query_string_data = redirect_location.split("#")[1]
                log_helper.debug("{0:20} {1:30} {2}".format("REFRESH TOKEN", "Querystring Data", query_string_data))
                oauth_data = urlparse.parse_qs(query_string_data)
                oauth_token = oauth_data["access_token"][0]
                log_helper.debug("{0:20} {1:30} {2}".format("REFRESH TOKEN", "Oauth Token", oauth_token))
                request_data = '{"accessToken":"' + oauth_token + '"}'
                handler.http_get(redirect_location, None)
                (token_res_code, token_res_data, token_res_header) = handler \
                    .http_post(CallerLookup.CallerLookupConstants.URL_TOKEN, request_data, {"content-type": "application/json",
                                                                       "referer": "https://www.truecaller.com/auth/google/callback",
                                                                       "origin": "https://www.truecaller.com"})
                if token_res_code != 200:
                    return None
                refreshed_token = json.loads(token_res_data.decode("utf-8"))
                if not "accessToken" in refreshed_token:
                    return None
                refreshed_access_token = refreshed_token["accessToken"]
                log_helper.debug("{0:20} {1:30} {2}".format("REFRESH TOKEN", "Success", refreshed_access_token))
                return refreshed_access_token

            def _get_restart_token():
                def wait_for(condition_function, timeout):
                    start_time = time.time()
                    while time.time() < start_time + timeout:
                        if condition_function():
                            return True
                        else:
                            time.sleep(0.1)
                    return False

                def get_otp():
                    if self.settings.otpsecret is None:
                        save_screenshot("TwoFactorAuth")
                        raise Exception("Sign in requires Two Step authentication but otpsecret has not been set.")
                    import pyotp
                    return pyotp.TOTP(self.settings.otpsecret)

                def is_token_created():
                    return driver.execute_script("return localStorage.getItem('tcToken') != null")

                def restore_cookies():
                    log_helper.debug("Restoring Cookies...")
                    cookies = handler.get_cookies(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS_NOFORM)
                    if cookies is None or len(cookies) == 0:
                        return
                    driver.get(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS_NOFORM)
                    for cookie in cookies:
                        try:
                            driver.add_cookie(cookie)
                        except:
                            ignore = True

                def save_cookies():
                    if driver.current_url.count(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS) == 0:
                        driver.get(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS_NOFORM)
                    handler.set_cookies(driver.get_cookies())

                def save_screenshot(name):
                    save_path = os.path.join(log_helper.path, "ScreenShots")
                    if not os.path.exists(save_path):
                        os.makedirs(save_path)
                    save_path = os.path.join(save_path, "{0}-{1}.png".format(
                        str(datetime.datetime.now().strftime("%Y%m%d-%H%M%S")), name))
                    log_helper.debug("Screenshot URL={0} Image=>{1}"
                                     .format(driver.current_url, save_path))
                    driver.save_screenshot(save_path)

                webdriver_log_path = os.path.join(os.path.dirname(self.settings.log_path),
                                                  os.path.splitext(os.path.basename(self.settings.log_path))[0]
                                                  + ".webdriver") \
                    if self.settings.is_debug else None
                log_helper.debug("WEBDRIVER LOG ({0})".format(webdriver_log_path))

                python_path = "C:\\Tools\\phantomjs\\bin\\phantomjs.exe"
                driver = webdriver.PhantomJS(executable_path=python_path, service_log_path=webdriver_log_path)

                try:

                    delay = 3
                    driver.set_window_size(600, 800)
                    restore_cookies()
                    url_login = _get_token_url()
                    log_helper.debug("GoTo URL={0}".format(url_login))
                    driver.get(url_login)
                    if driver.current_url.startswith(CallerLookup.CallerLookupConstants.URL_GOOGLE_ACCOUNTS):
                        log_helper.debug("Completing Logon Form (current_url={0})".format(driver.current_url))
                        email_element = driver.find_element_by_id('Email')
                        if email_element is not None:
                            if self.settings.username is None or len(self.settings.username) == 0:
                                raise Exception(
                                    "Configuration Error.  Username is not set {0}".format(self.settings.setting_path))
                            log_helper.debug("Completing Username (current_url={0})".format(driver.current_url))
                            email_element.send_keys(self.settings.username)
                            driver.find_element_by_id("next").click()
                        WebDriverWait(driver, delay).until(ec.element_to_be_clickable((By.ID, "Passwd")))
                        if self.settings.password is None or len(self.settings.password) == 0:
                            raise Exception(
                                "Configuration Error.  Password is required and is not available {0}".format(
                                    self.settings.setting_path))
                        driver.find_element_by_id('Passwd').send_keys(self.settings.password)
                        driver.find_element_by_id("signIn").click()
                        if driver.current_url.count("challenge/totp") > 0:
                            WebDriverWait(driver, delay).until(ec.element_to_be_clickable((By.ID, "totpPin")))
                            driver.find_element_by_id('totpPin').send_keys(get_otp())
                            driver.find_element_by_id("submit").click()
                        if driver.current_url.count("challenge/az") > 0:  # Phone Challenge
                            if not wait_for(is_token_created, 300):
                                raise Exception("Time out waiting for Remote Two Factor Authentication to "
                                                "accept login.")
                        if not driver.find_element_by_id('submit_approve_access') is None:
                            WebDriverWait(driver, delay).until(ec.element_to_be_clickable((By.ID,
                                                                                           "submit_approve_access")))
                            driver.find_element_by_id("submit_approve_access").click()
                        save_cookies()
                    driver.get(url_login)
                    if wait_for(is_token_created, delay):
                        return driver.execute_script("return localStorage.getItem('tcToken')")
                    save_screenshot("TimedOut")
                    return None
                except:
                    save_screenshot("ErrorScreenshot")
                    raise

            token = _get_refreshed_token()
            if token is None:
                token = _get_restart_token()
            if token is None:
                raise Exception("Failed to create new token")

            if token.startswith('"') and token.endswith('"'):
                token = token[1:-1]
            log_helper.debug("Saving Token to Cache")
            expiry = datetime.datetime.now() + datetime.timedelta(hours=1)
            CallerLookup.SettingHelper.set_setting(self.settings.setting_path, "Cache", "TokenExpiry",
                                                   expiry.strftime("%Y-%m-%d %H:%M:%S"))
            CallerLookup.SettingHelper.set_setting(self.settings.setting_path, "Cache", "Token", token)
            return token

    class SettingHelper(object):
        @staticmethod
        def get_setting(setting_path, setting_category, setting_name):
            """Get Application Setting"""
            config = configparser.ConfigParser()
            config.read(setting_path)
            if setting_category in config:
                if setting_name in config[setting_category]:
                    return config[setting_category][setting_name]
            return None

        @staticmethod
        def set_setting(setting_path, setting_category, setting_name, setting_value):
            config = configparser.ConfigParser()
            config.read(setting_path)
            if setting_category not in config:
                config.add_section(setting_category)
            config[setting_category][setting_name] = setting_value
            with open(setting_path, 'w') as configfile:
                config.write(configfile)

    class LogHelper(object):

        def __init__(self, settings):
            self.settings = settings
            self.path = os.path.dirname(self.settings.log_path)

            if len(self.path) > 0:
                if not os.path.exists(self.path):
                    os.makedirs(self.path)

            logging.getLogger().setLevel(logging.INFO)
            self._log = logging.getLogger("CallerLookup")
            handler = logging.FileHandler(self.settings.log_path)
            formatter = logging.Formatter('%(asctime)s   >>   %(levelname)8s   >>   %(message)s')
            handler.setFormatter(formatter)
            self._log.addHandler(handler)
            self._log.setLevel(logging.INFO)

            if self.settings.is_debug:
                logging.getLogger().setLevel(logging.DEBUG)
                self._log.setLevel(logging.DEBUG)
                req_log = logging.getLogger("requests.packages.urllib3")
                req_log.setLevel(logging.DEBUG)
                req_log.propagate = True
                req_handler = logging.FileHandler(os.path.join(self.path, "CallerLookup.HttpHandler.log"))
                req_handler.setFormatter(formatter)
                req_log.addHandler(req_handler)

        def debug(self, message):
            """Log Debug Message"""
            self._log.debug(self._encode(message))

        def info(self, message):
            """Log Info Message"""
            self._log.info(self._encode(message))

        def warning(self, message):
            """Log Warning Message"""
            self._log.warning(self._encode(message))

        def error(self, message):
            """Log Error Message"""
            self._log.error(self._encode(message))

        def _encode(self, message):
            if sys.version_info >= 3:
                return message.encode()
            elif sys.version_info >= (2, 6):
                return unicode(message, errors="replace")
            raise Exception("Python Version not supported.")

    class HttpHandler(object):

        class NoRedirect(HTTPErrorProcessor):
            def http_response(self, request, response):
                return response

            https_response = http_response

        def __init__(self, settings):
            self.settings = settings
            self._cookiejar = http.cookiejar.MozillaCookieJar()
            if os.path.isfile(self.settings.cookies_path):
                self._cookiejar.load(self.settings.cookies_path, ignore_discard=True)
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.save_cookies()

        def get_headers(self, append_headers=None, include_default=True):
            result = {}
            if append_headers is not None:
                result.update(append_headers)
            if include_default:
                result.update(CallerLookup.CallerLookupConstants.DEFAULT_HEADERS)
            return result

        def http_get(self, url, headers=None, include_default_headers=True):
            return self._http_request("GET", url, None, headers, include_default_headers)

        def http_post(self, url, data, headers=None, include_default_headers=True):
            return self._http_request("POST", url, data, headers, include_default_headers)

        def _http_request(self, method, url, data=None, headers=None, include_default_headers=True):

            log_helper.debug("===================")
            log_helper.debug("    {0} REQUEST".format(method))
            log_helper.debug("===================")
            log_helper.debug("{0:20s} {1}".format("URL", url))

            add_headers = self.get_headers(headers, include_default_headers)
            encoded_data = None
            if not data is None:
                encoded_data = bytes(data)
                add_headers.update({"content-length": len(encoded_data)})

            request = Request.Request(url, data=encoded_data, headers=add_headers)

            if not data is None:
                log_helper.debug("{0:20s} \n{1}".format("DATA", data))
                log_helper.debug("{0:20s} \n{1}".format("DATA (Encoded)", encoded_data))
            try:
                response = urlopen(request)
            finally:
                log_helper.debug("{0:20s} \n{1}".format("HEADERS", json.dumps(request.header_items())))

            log_helper.debug("===================")
            log_helper.debug("    {0} RESPONSE".format(method))
            log_helper.debug("===================")
            response_code = response.getcode()
            log_helper.debug("{0:20s} {1}".format("STATUS CODE", response_code))
            response_headers = response.info()
            import collections
            result_dict = collections.defaultdict(list)
            for key, value in response_headers.items():
                result_dict[key].append(value)
            log_helper.debug("{0:20s} \n{1}".format("HEADERS", json.dumps(result_dict)))

            if response_headers.get('Content-Encoding') == 'gzip':
                buf = StringIO.StringIO(response.read())
                f = gzip.GzipFile(fileobj=buf)
                response_data = f.read()
            else:
                response_data = response.read().decode("utf-8")

            log_helper.debug("{0:20s} {1}".format("DATA", response_data))

            return response_code, response_data, response_headers

        def get_cookies(self, full_url):
            url = urlparse(full_url)
            domain = url.netloc
            request_jar = requests.cookies.RequestsCookieJar()
            request_jar.update(self._cookiejar)
            return request_jar.get_dict(domain)

        def is_cookie_available(self, full_url):
            return len(self.get_cookies(full_url)) > 0

        def set_cookies(self, cookies):
            for c in cookies:
                self._cookiejar.set_cookie(self._get_cookie(c))

        def save_cookies(self):
            self._cookiejar.save(self.settings.cookies_path, ignore_discard=True, )

        @staticmethod
        def _get_cookie(item):
            if item is None:
                return None
            return http.cookiejar.Cookie(item["version"] if "version" in item else None,
                                         item["name"] if "name" in item else None,
                                         item["value"] if "value" in item else None,
                                         item["port"] if "port" in item else None,
                                         True if "port" in item else False,
                                         item["domain"] if "domain" in item else None,
                                         True if "domain" in item else False,
                                         True if "domain" in item and item["domain"].startswith(".") in item else False,
                                         item["path"] if "path" in item else None,
                                         True if "path" in item else False,
                                         True if "secure" in item else False,
                                         item["expiry"] if "expiry" in item else None,
                                         True if "discard" in item else False,
                                         item["comment"] if "comment" in item else None,
                                         item["comment_url"] if "comment_url" in item else None,
                                         None)


log_helper = None

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Reverse Caller Id',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Example: {0} --number +12024561111\n"
                                            "         {0} --number 02079309000 --region gb"
                                     .format(os.path.basename(__file__)))

    parser.add_argument("--number", "--n",
                        nargs="+",
                        dest="phone_numbers",
                        help="Phone number accepted in any standard format. When not in international format, the \
                                  default region parameter must be supplied",
                        action='append', required=True)

    parser.add_argument("--region", "--r",
                        dest="default_region",
                        default="gb",
                        help="The home region that the trunk belongs to.  Only required when phone number" \
                             " is supplied without an international dialling code.  Must be in CCN format.  See" \
                             "CountryCodes.json",
                        required=False)

    parser.add_argument("--path", "--p",
                        help="Working Directory",
                        dest="application_path",
                        required=False)

    parser.add_argument("--settings", "--s",
                        help="Path to Settings INI file",
                        dest="setting_path",
                        required=False)

    parser.add_argument("--cookies", "--c",
                        help="Path to Cookie store file",
                        dest="cookies_path",
                        required=False)

    parser.add_argument("--countrycodes", "--cc",
                        help="Path to Country Codes data file",
                        dest="country_data_path",
                        required=False)

    parser.add_argument("--logpath", "--l",
                        help="Path to Log Directory",
                        dest="log_path",
                        required=False)

    parser.add_argument("--username", "--un",
                        help="Google Account Username",
                        dest="username",
                        required=False)

    parser.add_argument("--password", "--pw",
                        help="Google Account Password",
                        dest="password",
                        required=False)

    parser.add_argument("--otpsecret", "--otp",
                        help="Google Account Two-Factor Auth Secret",
                        dest="otpsecret",
                        required=False)

    parser.add_argument("--debug",
                        help="Debug mode",
                        action="store_true",
                        dest="is_debug")

    args = vars(parser.parse_args())
    params = CallerLookup.CallerLookupParams(args)

    if not args["application_path"] is None:
        params.set_root_path(args["application_path"])

    try:

        lookup = CallerLookup(params)

        results = []

        for phone_number in args["phone_numbers"]:
            n = " ".join(phone_number)
            result = lookup.search(n, args["default_region"])
            results.append(result)

        print(json.dumps(results))

        exit(0)

    except Exception as e:

        print(str([{"Result": "Error", "Error": str(e)}]))
        raise
