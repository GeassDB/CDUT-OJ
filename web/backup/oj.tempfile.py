#!/usr/bin/env python

import pdb

import os.path
import os
import string
import re

import threading
import subprocess
import shlex
import random
import logging
import tempfile
import shutil
import signal

import pymongo
import bson
import tornado.ioloop
import tornado.web
import tornado.options
import tornado.httpserver
from tornado.options import define, options

import hashlib


#RFC 2822 Email Address
EMAIL_REGEX = re.compile(r"""(?:[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*|"(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21\x23-\x5b\x5d-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])*")@(?:(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?|[a-z0-9-]*[a-z0-9]:(?:[\x01-\x08\x0b\x0c\x0e-\x1f\x21-\x5a\x53-\x7f]|\\[\x01-\x09\x0b\x0c\x0e-\x7f])+)\])""")


define("port", default = 8888, type = int, help = "port to listen")
define("db_host", default = "localhost:27017", help = "database host")
define("db_name", default = "oj", help = "database name")

judge_event = threading.Event()

global_db = pymongo.MongoClient(host = options.db_host)[options.db_name]
if not __debug__:
    global_db.write_concern = {'w': 0}

exiting = False

compile_command = [
        "gcc -w -O2 -o {0} {0}.c",
        "g++ -w -O2 -o {0} {0}.cpp",
        ]
suffix = [
        ".c",
        ".cpp",
        ]


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
                (r"/", MainHandler),
                (r"/submit", SubmitHandler),

                (r"/status", StatusHandler),
                (r"/status/([^/]+)", StatusSourceHandler),

                (r"/user", UserHandler),
                (r"/user/list", UserListHandler),

                (r"/auth/login", LoginHandler),
                (r"/auth/logout", LogoutHandler),
                (r"/auth/register", RegisterHandler),

                (r"/problem/list", ProblemListHandler),
                (r"/problem/add", ProblemAddHandler),
                (r"/problem/edit", ProblemEditHandler),
                (r"/problem/(\d+)", ProblemHandler),
                ]

        settings = dict(
                title = "CDUT Online Judge",
                template_path = os.path.join(os.path.dirname(__file__), "templates"),
                static_path = os.path.join(os.path.dirname(__file__), "static"),
                languages = ["C", "C++", "Java", "Pascal"],
                login_url = "auth/login",
                cookie_secret = "CDUT_Online_Judge 0108",
                xsrf_cookies = True,
                debug = __debug__,
                )

        tornado.web.Application.__init__(self, handlers, **settings)

        JudgeThread().start()


class BaseHandler(tornado.web.RequestHandler):
    @property
    def db(self):
        return global_db

    def get_current_user(self):
        username = self.get_secure_cookie("username")
        if not username:
            return None

        current_userinfo = self.db.users.find_one({"_id" : username})
        return current_userinfo


class MainHandler(BaseHandler):
    def get(self):
        self.render("index.html")


class SubmitHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.render("submit.html")

    def post(self):
        if not self.get_argument("pid").isdigit()\
                or not self.db.problems.find_one({"_id" : int(self.get_argument("pid"))})\
                or not self.get_argument("lang").isdigit()\
                or int(self.get_argument("lang")) > len(self.settings["languages"]):
            raise tornado.web.HTTPError(400)
        else:
            self.db.status.ensure_index("_id", pymongo.DESCENDING)
            self.db.status.insert({
                    "username" : self.current_user["_id"],
                    "pid" : int(self.get_argument("pid")),
                    "language" : int(self.get_argument("lang")),
                    "result" : 0,
                    "code" : self.get_argument("src"),
                    }, w=1)

            self.set_cookie("def_lang", self.get_argument("lang"), expires_days=30)
            self.redirect("status?pid={}".format(self.get_argument("pid")))#TODO:add pid

        judge_event.set()
        logging.info("JudgeThread notified.")


class StatusHandler(BaseHandler):
    result_code = [
            "Waiting",
            "Judging",
            "Accepted",
            "Compile Error",
            "Wrong Answer",
            "Time Limit Exceeded",
            "Memory Limit Exceeded",
            ]

    def get(self):

        status_list = self.db.status.find({
            "_id" : {
                "$lt" : self.get_argument("top", bson.max_key.MaxKey()),
                "$gt" : self.get_argument("bottom", bson.min_key.MinKey())
                }}).limit(20).sort("_id", pymongo.DESCENDING)
        #TODO:add filter

        self.render("status.html",
                status_list = list(status_list)
                )


class StatusSourceHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self, sid):
        status = self.db.status.find_one({"_id" : bson.objectid.ObjectId(sid)})

        if not status:
            raise tornado.web.HTTPError(404)
        elif self.current_user["_id"] != status["username"]:
            raise tornado.web.HTTPError(403)
        else:
            self.render("source.html",
                    code = status["code"],
                    compile_info = status.get("compile_info", ""),
                    )


class UserHandler(BaseHandler):
    def get(self):
        pass


class UserListHandler(BaseHandler):
    def get(self):
        pass


class LoginHandler(BaseHandler):
    page_errors = [
            "Username does not exist.",
            "Wrong password.",
            ]
    def get(self):
        if self.current_user:
            self.redirect(self.get_argument("next", "/"))
            return
        self.render("login.html")

    def post(self):
        if not self.get_argument("username").replace('_','0').isalnum() \
                or len(self.get_argument("username")) > 32:
                    self.redirect("login?type=0")

        user_info = self.db.users.find_one({"_id" : self.get_argument("username")})

        if not user_info:
            self.redirect("login?type=0")
        elif hashlib.sha512(self.get_argument("username").lower()+\
                self.get_argument("password")).digest() == str(user_info["password"]):
            if "remember" in self.request.arguments:
                self.set_secure_cookie("username", user_info["_id"])
            else:
                self.set_secure_cookie("username", user_info["_id"], None)
            self.redirect(self.get_argument("next", "/"))
        else:
            self.redirect("login?type=1")


class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_all_cookies()
        self.redirect(self.get_argument("next", "/"))


class RegisterHandler(BaseHandler):
    page_errors = [
            "Invalid username.",
            "The entered passwords do not match.",
            "Invalid E-mail address.",
            "Invalid student id.",
            ]

    def get(self):
        if self.current_user:
            self.redirect(self.get_argument("next", "/"))
            return
        self.render("register.html")

    def post(self):
        if self.current_user:
            self.redirect(self.get_argument("next", "/"))
            return

        #TODO: change to atom operation
        if not self.get_argument("username").replace('_','0').isalnum() \
                or len(self.get_argument("username")) > 32 \
                or self.db.users.find_one({"_id" : self.get_argument("username")}):
            self.redirect("register?type=0&email={0}&stu_id={1}".format(
                self.get_argument("email"),
                self.get_argument("stu_id"),
                ))
        elif self.get_argument("password") != self.get_argument("confirm"):
            self.redirect("register?type=1&username={0}&email={1}&stu_id={2}".format(
                self.get_argument("username"),
                self.get_argument("email"),
                self.get_argument("stu_id"),
                ))
        elif not EMAIL_REGEX.match(self.get_argument("email")) \
                or len(self.get_argument("email")) > 320 \
                or self.db.users.find_one({"email" : self.get_argument("email")}):
            self.redirect("register?type=2&username={0}&stu_id={1}".format(
                self.get_argument("username"),
                self.get_argument("stu_id"),
                ))
        elif self.get_argument("stu_id") \
                and (not self.get_argument("stu_id").isdigit() \
                or len(self.get_argument("stu_id")) != 12 \
                or self.db.users.find_one({"stu_id" : self.get_argument("stu_id")})):
            self.redirect("register?type=3&username={0}&email={1}".format(
                self.get_argument("username"),
                self.get_argument("email"),
                ))
        else:
            self.db.users.ensure_index(["email", "stu_id"])
            self.db.users.insert({
                "_id" : self.get_argument("username"),
                "email" : self.get_argument("email"),
                "password" : bson.binary.Binary(
                    hashlib.sha512(self.get_argument("username").lower()+\
                            self.get_argument("password")).digest()),
                "stu_id" : self.get_argument("stu_id")
                })
            self.set_secure_cookie("username", str(self.get_argument("username")))
            self.redirect(self.get_argument("next", "/"))


class ProblemListHandler(BaseHandler):
    def get(self):
        if not self.get_cookie("problem_per_page"):
            self.set_cookie("problem_per_page", "30", expires_days=30)
            problem_per_page = 30
        else:
            problem_per_page = int(self.get_cookie("problem_per_page"))

        problem_list = self.db.problems.find({
            "_id" : {"$gte" : problem_per_page * self.get_argument("page", 0) - 1}
            }).limit(problem_per_page)

        self.render("problem_list.html",
                problem_list = problem_list,
                )


class ProblemAddHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        pass


class ProblemEditHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        pass


class ProblemHandler(BaseHandler):
    def get(self, pid):
        prob = self.db.problems.find_one({"_id" : int(pid)})

        if not prob:
            raise tornado.web.HTTPError(404)
        else:
            self.render("problem.html", prob = prob)


class JudgeThread(threading.Thread):
    def run(self):
        temp_dir = tempfile.mkdtemp()

        while not exiting:
            judging_submit = global_db.status.find_and_modify(
                    query = { "result" : 0 },
                    update = { "$set" : { "result" : 1 } }
                    )
            while judging_submit:
                logging.info("judging {}".format(str(judging_submit["_id"])))

                exe_path = temp_dir + '/' + str(judging_submit["_id"])

                code = open(exe_path + suffix[judging_submit["language"]], 'w')
                code.write(judging_submit["code"])
                code.close()

                p = subprocess.Popen(shlex.split(
                    compile_command[judging_submit["language"]].\
                            format(str(judging_submit["_id"]))),
                            stdout = subprocess.PIPE,
                            stderr = subprocess.STDOUT,
                            cwd = temp_dir,
                            )
                judging_submit["compile_info"] = p.communicate()[0]

                os.remove(exe_path + suffix[judging_submit["language"]])

                if p.returncode:
                    judging_submit["result"] = 3
                    global_db.status.save(judging_submit)
                else:
                    problem = global_db.problems.find_one({ "_id" : judging_submit["pid"] })
                    for tp in problem["tp_list"]:
                        p = subprocess.Popen(exe_path,
                                stdin = subprocess.PIPE,
                                stdout = subprocess.PIPE,
                                cwd = temp_dir,
                                )

                    os.remove(exe_path)

                judging_submit = global_db.status.find_and_modify(
                        query = { "result" : 0 },
                        update = { "$set" : { "result" : 1 } }
                        )

            judge_event.clear()
            logging.info("JudgeThread waiting.")
            judge_event.wait(30)

        os.rmdir(temp_dir)


def signal_handler(signum, frame):
    global exiting
    tornado.ioloop.IOLoop.instance().stop()
    exiting = True


if __name__ == "__main__":
    tornado.options.parse_command_line()
    signal.signal(signal.SIGINT, signal_handler)
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()
