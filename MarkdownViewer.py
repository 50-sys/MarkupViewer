#!/usr/bin/env
# coding: utf8
"""
MarkdownViewer
* Description: MarkdownViewer is a simple Markdown file viewer written in
  Python. I wanted an easy way to view Markdown files, so I hacked this
  together...it isn't pretty, but it is functional. The view will be refreshed
  when the opened file is saved allowing you to use whatever editor you'd like
  and see the results immediately.

* Dependencies: PyQt4 and Markdown (the Python package).

* Usage: python MarkdownViewer.py <file>
  To automatically open a Markdown file with this viewer in Windows, associate
  the filetype with the included .bat file. You can apply themes by dropping
  your stylesheets in the stylesheets/ directory next to this script and
  selecting one from the Style menu.

* Note: Feel free to make improvements. Fork and send me a pull request.
  http://

* Links
 - PyQt4: http://www.riverbankcomputing.com/software/pyqt/download
 - Markdown (available via PIP): http://pypi.python.org/pypi/Markdown
 - Learn more about Markdown and the Markdown syntax here:
   http://daringfireball.net/projects/markdown/
 - Installed stylesheets from https://github.com/jasonm23/markdown-css-themes

Matthew Borgerson <mborgerson@gmail.com>
"""
import sys, time, os, webbrowser, importlib, itertools, locale, io, yaml
from PyQt4 import QtCore, QtGui, QtWebKit

sys_enc = locale.getpreferredencoding()


class Settings:
    user_source = os.path.join(os.getenv('APPDATA'), 'MarkdownViewer/settings.yaml')
    app_source  = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.yaml')
    settings_file = user_source if os.path.exists(user_source) else app_source
    with io.open(settings_file, 'r', encoding='utf8') as f:
        settings = yaml.safe_load(f)

    @classmethod
    def get(self, key=''):
        return self.settings[key]


class SetuptheReader:
    """a knot of methods related to readers: which one need to be used, is it available etc.
    basic usecase:
        reader, writer = SetuptheReader._for(filename)
        html = writer(unicode_object)
    """
    readers = Settings.get('formats')

    @classmethod
    def _for(self, filename):
        file_ext = filename.split('.')[-1].lower()
        return self.is_available(self.reader(file_ext))

    @classmethod
    def mapping_formats(self, readers=''):
        ''' get    dict {'reader1': 'ext1 ext2 ...', ...}
            return dict {'ext1': 'reader1', ...}'''
        # why: make it simple for user to redefine readers for file extensions
        omg = lambda d: itertools.imap(lambda t: (t, d[0]), d[1].split())
        return {e: r for e, r in itertools.chain(*itertools.imap(omg, readers.iteritems()))}

    @classmethod
    def readers_names(self):
        return self.readers.keys()

    @classmethod
    def reader(self, file_ext):
        formats = self.mapping_formats(self.readers)
        if file_ext in formats.keys():
            reader = formats[file_ext]
        else:
            reader = Settings.get('no_extension')
        return reader

    @classmethod
    def is_available(self, reader):
        via_pandoc = Settings.get('via_pandoc')
        if via_pandoc and (reader != 'creole'):
            try:            subprocess.call(['pandoc', '-v'])
            except OSError: via_pandoc = False
            else:           return (reader, 'pandoc')
        elif not via_pandoc or reader == 'creole':
            writers = {
                'creole'  : ('creole',        'creole2html'),
                'markdown': ('markdown',      'markdown'),
                'rst'     : ('docutils.core', 'publish_parts'),
                'textile' : ('textile',       'textile')
                }
            fail = (KeyError, ImportError)
            try:
                writer = getattr(importlib.import_module(writers[reader][0]), writers[reader][1])
            except fail:
                return (reader, False)
            else:
                return (reader, writer)

script_dir = os.path.dirname(os.path.realpath(__file__))
stylesheet_dir = os.path.join(script_dir, 'stylesheets/')
stylesheet_default = Settings.get('style')

class App(QtGui.QMainWindow):
    def __init__(self, parent=None, filename=''):
        QtGui.QMainWindow.__init__(self, parent)

        # Configure the window
        # TODO: remember/restore geometry in/from @settings
        self.setGeometry(0, 488, 640, 532)
        # TODO: full path / only name @settings
        self.setWindowTitle(u'%s — MarkdownViewer' % unicode(os.path.join(os.getcwd(), filename), sys_enc))
        self.setWindowIcon(QtGui.QIcon('markdown-mark.ico'))
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MarkdownViewer')
        except: pass

        # Add the WebView control
        self.web_view = QtWebKit.QWebView()
        self.setCentralWidget(self.web_view)

        # Enable plugins (Flash, QiuckTime etc.)
        QtWebKit.QWebSettings.globalSettings().setAttribute(3, Settings.get('plugins'))
        # Open links in default browser
        # TODO: ¿ non-default browser @settings ?
        self.web_view.linkClicked.connect(lambda url: webbrowser.open_new_tab(url.toString()))

        # Setup menu bar
        # TODO: hide menu?
        menubar = self.menuBar()
        fileMenu = menubar.addMenu('&File')
        searchAction = QtGui.QAction('&Find', self)
        searchAction.setShortcut('Ctrl+f')
        searchAction.triggered.connect(self.search_panel)
        fileMenu.addAction(searchAction)
        # TODO: meta action for ESC key: hide search panel, then close the window
        exitAction = QtGui.QAction('E&xit', self)
        exitAction.setShortcut('ESC')
        exitAction.setStatusTip('Exit application')
        exitAction.triggered.connect(QtGui.qApp.quit)
        fileMenu.addAction(exitAction)

        # Add style menu
        if os.path.exists(stylesheet_dir):
            default = ''
            sheets = []
            for f in os.listdir(stylesheet_dir):
                if not f.endswith('.css'): continue
                sheets.append(QtGui.QAction(f, self))
                if len(sheets) < 10:
                    sheets[-1].setShortcut('Ctrl+%d' % len(sheets))
                sheets[-1].triggered.connect(
                    lambda x, stylesheet=f: self.set_stylesheet(stylesheet))
            styleMenu = menubar.addMenu('&Style')
            for item in sheets:
                styleMenu.addAction(item)
            self.set_stylesheet(stylesheet_default)
        self.toc = self.menuBar().addMenu('Table of &content')
        self.stats_menu = self.menuBar().addMenu('Stats')

        # Start the File Watcher Thread
        thread = WatcherThread(filename)
        self.connect(thread, QtCore.SIGNAL('update(QString)'), self.update)
        thread.start()
        self.filename = filename
        self.update('')

    def update(self, text):
        prev_doc    = self.web_view.page().currentFrame()
        prev_size   = prev_doc.contentsSize()
        prev_scroll = prev_doc.scrollPosition()
        self.web_view.setContent(QtCore.QString(text).toUtf8(), baseUrl=QtCore.QUrl('file:///'+unicode(os.path.join(os.getcwd(), self.filename).replace('\\', '/'), sys_enc)))
        self.current_doc  = self.web_view.page().currentFrame()
        current_size = self.current_doc.contentsSize()
        if prev_scroll.y() > 0: # self.current_doc.scrollPosition() is always 0
            ypos = prev_scroll.y() - (prev_size.height() - current_size.height())
            self.current_doc.scroll(0, ypos)
        # Delegate links to default browser
        self.web_view.page().setLinkDelegationPolicy(QtWebKit.QWebPage.DelegateAllLinks)
        # Statistics:
        u'''This is VERY big deal. For instance, how many words:
                « un lien »
            Two? One? many markdown editors claims that it’s four (sic!) words… ugh…
            Another examples:
                1.5 litres (English)
                1,5 литра (Russian)
                10.000 = 10,000 = 10 000
            Unfortunately, even serious software (e.g. http://liwc.net) fails to
            count properly. The following implementation is not perfect either,
            still, more accurate than many others.
            TODO: statistics — decimals is a huge problem
        '''
        text  = unicode(self.current_doc.toPlainText())
        filtered_text = text.replace('\'', '').replace(u'’', '')
        for c in ('"', u'…', '...', '!', '?', u'¡', u'¿', '/', '\\', '*', ',' , u'‘', u'”', u'“', u'„', u'«', u'»', u'—', '&', '\n'):
            filtered_text = filtered_text.replace(c, ' ')
        words = filtered_text.split()
        lines = text.split('\n')
        text  = text.replace('\n', '')
        self.stats_menu.clear()
        self.stats_menu.setTitle( str(len(words)) + ' &words')
        self.stats_menu.addAction(str(len(text))  + ' characters')
        self.stats_menu.addAction(str(len(lines)) + ' lines')
        # TOC
        self.toc.clear()
        headers = []
        for i in xrange(1, 6):
            first = self.current_doc.findFirstElement('h%d'%i)
            if len(first.tagName()) > 0:
                headers.append(first)
                break
        while True:
            next = first.nextSibling()
            if len(next.tagName()) == 0:
                break
            else:
                first = next
                if 'H' in next.tagName(): headers.append(next)
        for n, h in enumerate(headers, start=1):
            try:               indent = int(h.tagName()[1:])
            except ValueError: break # cannot make it integer, means no headers
            vars(self)['toc_nav%d'%n] = QtGui.QAction('h%d:%s%s'% (indent, ' '*4*indent , h.toPlainText()), self)
            vars(self)['toc_nav%d'%n].triggered[()].connect(lambda header=h: self._scroll(header))
            self.toc.addAction(vars(self)['toc_nav%d'%n])

    def _scroll(self, header):
        self.current_doc.setScrollPosition(QtCore.QPoint(0, header.geometry().top()))

    def set_stylesheet(self, stylesheet='default.css'):
        # QT only works when the slashes are forward??
        full_path = 'file://' + os.path.join(stylesheet_dir, stylesheet)
        full_path = full_path.replace('\\', '/')
        url = QtCore.QUrl(full_path)
        self.web_view.settings().setUserStyleSheetUrl(url)

    def search_panel(self):
        search_bar = QtGui.QToolBar()
        for v, t in (('close', u'×'), ('case', 'Aa'), ('wrap', u'∞'), ('high', u'💡'), ('next', u'↓'), ('prev', u'↑')):
            vars(self)[v] = QtGui.QPushButton(t, self)
        self.field = QtGui.QLineEdit()
        def _toggle_btn():
            self.field.setFocus()
            self.find(self.field.text())
        for w in (self.close, self.case, self.wrap, self.high, self.field, self.next, self.prev):
            search_bar.addWidget(w)
            if type(w) == QtGui.QPushButton:
                w.setFlat(True)
                w.setFixedWidth(36)
                if w is self.case or w is self.wrap or w is self.high:
                    w.setCheckable(True)
                    w.setFixedWidth(24)
                    w.clicked.connect(_toggle_btn)
        self.addToolBar(0x8, search_bar)
        self.field.textChanged.connect(self.find)
        self.field.setFocus()

    def find (self, text):
        p = self.web_view.page()
        case = p.FindFlags(2) if self.case.isChecked() else p.FindFlags(0)
        wrap = p.FindFlags(4) if self.wrap.isChecked() else p.FindFlags(0)
        high = p.FindFlags(8) if self.high.isChecked() else p.FindFlags(0)
        p.findText('', p.FindFlags(8)) # clear prev highlight
        p.findText(text, wrap | case | high)

class WatcherThread(QtCore.QThread):
    def __init__(self, filename):
        QtCore.QThread.__init__(self)
        self.filename = filename

    def __del__(self):
        self.wait()

    def run(self):
        last_modified = 0
        reader, writer = SetuptheReader._for(self.filename)
        if writer == 'pandoc':
            pandoc_path     = Settings.get('pandoc_path')
            pandoc_markdown = Settings.get('pandoc_markdown')
            pandoc_args     = Settings.get('pandoc_args')
        if not writer:
            # TODO: make a proper error message
            return reader
        while True:
            current_modified = os.path.getmtime(self.filename)
            if last_modified != current_modified:
                last_modified = current_modified
                if writer == 'pandoc':
                    reader = pandoc_markdown if reader == 'markdown' else reader
                    args = ('%s --from=%s %s'%(pandoc_path, reader, pandoc_args)).split() + [self.filename]
                    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                    html = p.communicate()[0].decode('utf8')
                else:
                    with io.open(self.filename, 'r', encoding='utf8') as f:
                        text = f.read()
                        if reader == 'rst':
                            html = writer(text, writer_name='html', settings_overrides={'stylesheet_path': ''})['body']
                        else:
                            html = writer(text)
                self.emit(QtCore.SIGNAL('update(QString)'), html)
            time.sleep(0.5)

def main():
    if len(sys.argv) != 2: return
    app = QtGui.QApplication(sys.argv)
    # if not (via_pandoc or via_markdown):
    #     QtGui.QMessageBox.critical(QtGui.QWidget(),'MarkdownViewer cannot convert a file',
    #         'Please, install one of the following packages:<br>'
    #         u'• <a href="https://pythonhosted.org/Markdown/install.html">Markdown</a><br>'
    #         u'• <a href="http://johnmacfarlane.net/pandoc/installing.html">Pandoc</a>')
    if True:
        test = App(filename=sys.argv[1])
        test.show()
        app.exec_()

if __name__ == '__main__':
    main()
