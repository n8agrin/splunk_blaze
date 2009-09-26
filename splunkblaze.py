#!/usr/bin/env python

import os.path
import time
import splunk.auth
import splunk.search
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import uimodules

from tornado.options import define, options

define("port", default=8888, help="web server port", type=int)
define("splunk_host_path", default="https://localhost:8089", help="splunk server scheme://host:port (Use http over https for performance bump!)")
define("splunk_username", default="admin", help="splunk user")
define("splunk_password", default="changeme", help="splunk password")

class AsyncSearch(object):
    def search(self, search, sessionKey, hostPath, callback):
        job = splunk.search.dispatch(search, sessionKey=sessionKey, hostPath=hostPath)
        job.setFetchOption(
            segmentationMode='full',
            maxLines=500,
        )       
        return callback(job)

class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/search", SearchHandler),            
        ]
        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            cookie_secret="e220cf903f537500f6cfcaccd64df14d",
            xsrf_cookies=True,
            ui_modules=uimodules,            
        )
        tornado.web.Application.__init__(self, handlers, **settings)
        
        #Have one global splunk session_key accross all users.
        self.session_key = splunk.auth.getSessionKey(options.splunk_username, options.splunk_password, hostPath=options.splunk_host_path)
        
class BaseHandler(tornado.web.RequestHandler):
    @property
    def session_key(self):
        return self.application.session_key
    
class HomeHandler(BaseHandler):
    def get(self):
        self.render("index.html")

class SearchHandler(BaseHandler):
    @tornado.web.asynchronous
    def post(self):
        search = AsyncSearch()
        search.search(self.get_argument("search"), self.session_key, options.splunk_host_path, self.async_callback(self.on_job))
        
    def on_job(self, job):
        maxtime = 10
        pause = 0.05
        lapsed = 0.0
        event_count = 0
        rendered_header = False
        
        xslt = '''<?xml version="1.0" encoding="UTF-8"?>
        <xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
            <xsl:strip-space elements="*" />
            <xsl:preserve-space elements="v sg" />
            <xsl:output method="html" indent="no" />
            <xsl:template match="/">
                <xsl:apply-templates select="v" />
            </xsl:template>
            <xsl:template match="v">
                <xsl:apply-templates />
            </xsl:template>
            <xsl:template match="sg">
                <em>
                    <xsl:attribute name="class">
                        <xsl:text>t</xsl:text>
                        <xsl:if test="@h">
                            <xsl:text> a</xsl:text>
                        </xsl:if>
                    </xsl:attribute>
                    <xsl:apply-templates />
                </em>
            </xsl:template>
        </xsl:stylesheet>
        '''
        
        while not job.isDone:
            new_event_count = job.eventCount
            if new_event_count == event_count:
                if maxtime >= 0 and lapsed > maxtime:
                    # job.pause() # stop! no more hammer time!
                    break
                time.sleep(pause)
                lapsed += pause
                continue
            
            if new_event_count > 0 and not rendered_header:
                self.write(self.render_string('_search_header.html', job=job))
                self.write('FOOO!!!!')
                rendered_header = True
            
            if new_event_count > event_count+10:
                # self.render_string('_search_event.html', events=job.events[event_count:event_count+10], xslt=xslt)
                self.write('events')
                event_count = event_count+10        
            else:
                # self.render_string('_search_event.html', events=job.events[event_count:new_event_count-1], xslt=xslt)
                self.write('events')
                event_count = new_event_count
                
            # Clean up
            lapsed += pause
            if maxtime >= 0 and lapsed > maxtime:
                job.pause() # stop! no more hammer time!
                break
        
        if job.isDone and not rendered_header:
            self.render("search.html", job=job, xslt=xslt)
            return
        self.finish()
        # self.render("search.html", job=job, xslt=xslt)
        

def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()
 
 
if __name__ == "__main__":
    main()