#!/usr/bin/env python3

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
import datetime

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
        "gcc -w -O2 -o {0} -x c -",
        "g++ -w -O2 -o {0} -x c++ -",
        ]

#logging.basicConfig(filename='oj.log',level=logging.DEBUG)


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
                (r"/", MainHandler),
                (r"/submit", SubmitHandler),

                (r"/status", StatusHandler),
                (r"/status/([^/]+)", StatusSourceHandler),

                #(r"/user/([^/]+)", UserHandler),
                (r"/userlist", UserListHandler),

                (r"/auth/login", LoginHandler),
                (r"/auth/logout", LogoutHandler),

                (r"/problem/list", ProblemListHandler),
                #(r"/problem/add", ProblemAddHandler),
                #(r"/problem/(\d+)/edit", ProblemEditHandler),
                (r"/problem/(\d+)", ProblemHandler),
                #(r"/problem/add_tp", ProblemAddTestPointHandler),
                ]

        settings = dict(
                title = "CDUT Online Judge",
                template_path = os.path.join(os.path.dirname(__file__), "templates"),
                static_path = os.path.join(os.path.dirname(__file__), "static"),
                languages = ["C", "C++", "Java", "Pascal"],
                login_url = "/auth/login",
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

    @tornado.web.authenticated
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
        logging.debug("JudgeThread notified.")


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
                "$lt" : bson.objectid.ObjectId(self.get_argument("top",
                    "ffffffffffffffffffffffff")),
                "$gt" : bson.objectid.ObjectId(self.get_argument("bottom",
                    "000000000000000000000000"))
                },
            }).limit(20).sort("_id", pymongo.DESCENDING)
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
        user_list = self.db.users.find().sort("score", pymongo.DESCENDING)
        self.render("user_list.html",
                user_list = list(user_list)
                )


class LoginHandler(BaseHandler):
    page_errors = [
            "Invalid name.",
            "Wrong password.",
            "Invalid student id.",
            "Invalid student id & name pair.",
            ]

    def get(self):
        if self.current_user:
            self.redirect(self.get_argument("next", "/"))
            return
        self.render("login.html")

    def post(self):
        if self.current_user:
            self.redirect(self.get_argument("next", "/"))
            return

        #TODO: change to atom operation
        if not self.get_argument("stu_id").isdigit() \
                or len(self.get_argument("stu_id")) != 12:
            self.redirect("login?type=2")
        elif len(self.get_argument("username")) > 32 :
            self.redirect("login?type=0&stu_id={}".format(
                self.get_argument("stu_id"),
                ))
        elif self.get_argument("password") != "PDA_Contest":
            self.redirect("login?type=1&stu_id={}".format(
                self.get_argument("stu_id"),
                ))
        elif self.db.users.find_one({"_id" : self.get_argument("stu_id")}):
            if self.db.users.find_one({"_id" : self.get_argument("stu_id")})["name"] == \
                    self.get_argument("username"):
                if "remember" in self.request.arguments:
                    self.set_secure_cookie("username", str(self.get_argument("stu_id")))
                else:
                    self.set_secure_cookie("username", str(self.get_argument("stu_id")), None)
                self.redirect(self.get_argument("next", "/"))
            else:
                self.redirect("login?type=3")
        else:
            self.db.users.ensure_index("score", pymongo.DESCENDING)
            self.db.users.insert({
                "_id" : self.get_argument("stu_id"),
                "name" : self.get_argument("username"),
                "ac_list" : [],
                "score" : 0,
                })
            if "remember" in self.request.arguments:
                self.set_secure_cookie("username", str(self.get_argument("stu_id")))
            else:
                self.set_secure_cookie("username", str(self.get_argument("stu_id")), None)
            self.redirect(self.get_argument("next", "/"))


class LogoutHandler(BaseHandler):
    def get(self):
        self.clear_all_cookies()
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
                problem_list = list(problem_list),
                )


class ProblemAddHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.render("problem_add.html")

    @tornado.web.authenticated
    def post(self):
        self.db.problems.insert({
            "_id" : int(self.get_argument("pid")),
            "title" : self.get_argument("title"),
            "content" : self.get_argument("content"),
            "score" : int(self.get_argument("score")),
            "submit_num" : 0,
            "accept_num" : 0,
            "tp_list" : [],
            "time" : datetime.datetime.utcnow(),
            })
        self.redirect("list")


class ProblemEditHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        pass


class ProblemAddTestPointHandler(BaseHandler):
    @tornado.web.authenticated
    def get(self):
        self.render("problem_add_tp.html")

    @tornado.web.authenticated
    def post(self):
        print(self.request.arguments)
        print(type(self.request.arguments["input"][0]))
        p = self.db.problems.find_one({"_id" : int(self.get_argument("pid"))})
        p["tp_list"].append({
            "in" : self.request.arguments["input"][0],
            "out" : self.request.arguments["output"][0],
            })
        self.db.problems.save(p)
        self.redirect("list")



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

        #TODO:optimize logic
        while not exiting:
            judging_submit = global_db.status.find_and_modify(
                    query = { "result" : 0 },
                    update = { "$set" : { "result" : 1 } }
                    )
            while judging_submit:
                logging.info("judging {}".format(str(judging_submit["_id"])))

                exe_path = temp_dir + '/' + str(judging_submit["_id"])

                p = subprocess.Popen(shlex.split(
                    compile_command[judging_submit["language"]].\
                            format(str(judging_submit["_id"]))),
                            stdin = subprocess.PIPE,
                            stdout = subprocess.PIPE,
                            stderr = subprocess.STDOUT,
                            cwd = temp_dir,
                            )
                try:
                    judging_submit["compile_info"] = p.communicate(judging_submit["code"])[0]
                except UnicodeEncodeError:
                    p.terminate()
                    judging_submit["result"] = 3
                else:
                    if p.returncode:
                        judging_submit["result"] = 3
                    else:
                        problem = global_db.problems.find_one({ "_id" : judging_submit["pid"] })
                        for tp in problem["tp_list"]:
                            p = subprocess.Popen(
                                    exe_path,
                                    stdin = subprocess.PIPE,
                                    stdout = subprocess.PIPE,
                                    cwd = temp_dir,
                                    )
                            t = threading.Timer(2, terminate_timer, [p])
                            t.start()

                            #tp["out"] = output
                            if p.communicate(tp["in"])[0] != tp["out"]:
                                t.cancel()
                                if p.returncode == -15 :
                                    judging_submit["result"] = 5
                                else:
                                    logging.debug(p.returncode)
                                    judging_submit["result"] = 4
                                break
                            t.cancel()
                        else:
                            #global_db.problems.save(problem)
                            judging_submit["result"] = 2
                            u = global_db.users.find_one({ "_id" : judging_submit["username"] })
                            if not judging_submit["pid"] in u["ac_list"]:
                                u["ac_list"].append(judging_submit["pid"])
                                u["score"] += problem.get("score", 10)
                                global_db.users.save(u)

                        os.remove(exe_path)

                global_db.status.save(judging_submit)

                judging_submit = global_db.status.find_and_modify(
                        query = { "result" : 0 },
                        update = { "$set" : { "result" : 1 } }
                        )

            judge_event.clear()
            if not exiting:
                logging.debug("JudgeThread waiting.")
                judge_event.wait(60)

        os.rmdir(temp_dir)


def signal_handler(signum, frame):
    global exiting
    tornado.ioloop.IOLoop.instance().stop()
    exiting = True
    judge_event.set()

def kill_timer(p):
    logging.debug("kill!")
    p.kill()

def terminate_timer(p):
    logging.debug("terminate!")
    p.terminate()


if __name__ == "__main__":
    tornado.options.parse_command_line()
    signal.signal(signal.SIGINT, signal_handler)
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()
