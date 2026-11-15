"""Small, short-lived Poppler GLib bridge for standard PDF annotations."""
import ctypes as C
import json
import math
import os
from pathlib import Path
import sys
import tempfile

MAX_MARKS = 200
MAX_NOTE = 1000
MAX_REQUEST = 900_000
P = C.c_void_p
D = C.c_double


class Point(C.Structure):
    _fields_ = [('x', D), ('y', D)]


class Quad(C.Structure):
    _fields_ = [(f'p{i}', Point) for i in range(1, 5)]


class Rectangle(C.Structure):
    _fields_ = [(key, D) for key in ('x1', 'y1', 'x2', 'y2')]


class Mapping(C.Structure):
    _fields_ = [('area', Rectangle), ('annotation', P)]


class List(C.Structure):
    _fields_ = [('data', C.POINTER(Mapping)), ('next', P), ('previous', P)]


def bind(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.argtypes = args
    fn.restype = result
    return fn


class Poppler:
    def __init__(self):
        pdf = C.CDLL('libpoppler-glib.so.8')
        glib = C.CDLL('libglib-2.0.so.0')
        gobj = C.CDLL('libgobject-2.0.so.0')
        self.load = bind(pdf, 'poppler_document_new_from_file', P, C.c_char_p, C.c_char_p, C.POINTER(P))
        self.save = bind(pdf, 'poppler_document_save', C.c_int, P, C.c_char_p, C.POINTER(P))
        self.get_page = bind(pdf, 'poppler_document_get_page', P, P, C.c_int)
        self.get_size = bind(pdf, 'poppler_page_get_size', None, P, C.POINTER(D), C.POINTER(D))
        self.mappings = bind(pdf, 'poppler_page_get_annot_mapping', P, P)
        self.free_mappings = bind(pdf, 'poppler_page_free_annot_mapping', None, P)
        self.contents = bind(pdf, 'poppler_annot_get_contents', P, P)
        self.annot_type = bind(pdf, 'poppler_annot_get_annot_type', C.c_int, P)
        self.note = bind(pdf, 'poppler_annot_text_new', P, P, C.POINTER(Rectangle))
        self.highlight = bind(pdf, 'poppler_annot_text_markup_new_highlight', P, P, C.POINTER(Rectangle), P)
        self.set_text = bind(pdf, 'poppler_annot_set_contents', None, P, C.c_char_p)
        self.add = bind(pdf, 'poppler_page_add_annot', None, P, P)
        self.array = bind(glib, 'g_array_new', P, C.c_int, C.c_int, C.c_uint)
        self.append = bind(glib, 'g_array_append_vals', P, P, P, C.c_uint)
        self.free_array = bind(glib, 'g_array_unref', None, P)
        self.free = bind(glib, 'g_free', None, P)
        self.free_error = bind(glib, 'g_error_free', None, P)
        self.unref = bind(gobj, 'g_object_unref', None, P)

    def checked(self, fn, message, *args):
        error = P()
        try:
            result = fn(*args, C.byref(error))
            if not result:
                raise ValueError(message)
            return result
        finally:
            if error:
                self.free_error(error)

    def make_mark(self, doc, page, kind, points, contents):
        w, h = D(), D()
        self.get_size(page, C.byref(w), C.byref(h))
        if not all(math.isfinite(v) and 0 < v <= 1_000_000 for v in (w.value, h.value)):
            raise ValueError('The page has an unsupported size.')
        if kind == 'highlight':
            x1, y1, x2, y2 = points
            left, right = x1 * w.value, x2 * w.value
            top, bottom = (1-y1) * h.value, (1-y2) * h.value
            rect = Rectangle(left, bottom, right, top)
            quad = Quad(Point(left, top), Point(right, top), Point(left, bottom), Point(right, bottom))
            vertices = self.array(0, 0, C.sizeof(Quad))
            try:
                self.append(vertices, C.byref(quad), 1)
                annot = self.highlight(doc, C.byref(rect), vertices)
            finally:
                self.free_array(vertices)
        else:
            x, y = points
            side = min(18, w.value, h.value)
            left = min(x * w.value, w.value - side)
            top = max(side, (1-y) * h.value)
            rect = Rectangle(left, top-side, left+side, top)
            annot = self.note(doc, C.byref(rect))
        if not annot:
            raise ValueError('Could not create the annotation.')
        try:
            if contents:
                self.set_text(annot, contents.encode('utf-8'))
            self.add(page, annot)
        finally:
            self.unref(annot)

    def page_notes(self, page):
        mappings = node = self.mappings(page)
        notes = []
        try:
            while node and len(notes) < MAX_MARKS:
                obj = C.cast(node, C.POINTER(List)).contents
                annotation = obj.data.contents.annotation
                # POPPLER_ANNOT_TEXT and POPPLER_ANNOT_HIGHLIGHT.
                if self.annot_type(annotation) in (1, 9):
                    contents = self.contents(annotation)
                    if contents:
                        try:
                            data = C.cast(contents, C.c_char_p).value
                            if data:
                                notes.append(data[:MAX_NOTE * 4].decode('utf-8', 'replace')[:MAX_NOTE])
                        finally:
                            self.free(contents)
                node = obj.next
        finally:
            if mappings:
                self.free_mappings(mappings)
        return notes


def revision(path):
    value = path.stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def validate(mark):
    kind, number, points, contents = mark
    if type(number) is not int or not 1 <= number <= 99_999_999:
        raise ValueError('Invalid annotation page.')
    lengths = {'highlight': 4, 'note': 2}
    if kind not in lengths or len(points) != lengths[kind] or not all(
            isinstance(v, (float, int)) and 0 <= v <= 1 for v in points):
        raise ValueError('Invalid annotation position.')
    if kind == 'highlight' and not (points[0] < points[2] and points[1] < points[3]):
        raise ValueError('The highlight area is empty.')
    if not isinstance(contents, str) or len(contents) > MAX_NOTE or '\0' in contents:
        raise ValueError('Invalid annotation text.')
    return kind, number, points, contents


def execute(operation, source, request, destination=None):
    source = Path(source).absolute()
    if operation == 'save':
        expected = request['revision']
        if revision(source) != expected:
            raise ValueError('The original PDF changed. Reopen it before adding markup.')
        marks = request['marks']
        if not 1 <= len(marks) <= MAX_MARKS:
            raise ValueError('Invalid annotation count.')
        marks = [validate(mark) for mark in marks]
        destination = Path(destination).absolute()
        if os.path.lexists(destination):
            raise ValueError('Choose a new filename; no existing PDF will be replaced.')
    bridge = Poppler()
    doc = bridge.checked(bridge.load, 'This PDF could not be opened.', source.as_uri().encode(), None)
    try:
        if operation == 'notes':
            page = bridge.get_page(doc, request['page'] - 1)
            if not page:
                raise ValueError('Could not read notes on this page.')
            try:
                return bridge.page_notes(page)
            finally:
                bridge.unref(page)
        for kind, number, points, contents in marks:
            page = bridge.get_page(doc, number - 1)
            if not page:
                raise ValueError('An annotation refers to an unavailable page.')
            try:
                bridge.make_mark(doc, page, kind, points, contents)
            finally:
                bridge.unref(page)
        # The temporary file is private and on the destination filesystem.
        # Linking the complete PDF fails atomically if another file claims the name.
        with tempfile.TemporaryDirectory(prefix='.mellipi-pdf-', dir=destination.parent) as directory:
            draft = Path(directory) / 'annotated.pdf'
            bridge.checked(bridge.save, 'Poppler could not save the annotated PDF.', doc, draft.as_uri().encode())
            if revision(source) != expected:
                raise ValueError('The original PDF changed during export; no copy was saved.')
            os.chmod(draft, 0o600)
            with draft.open('rb') as stream:
                os.fsync(stream.fileno())
            try:
                os.link(draft, destination)
            except FileExistsError as error:
                raise ValueError('Choose a new filename; no existing PDF will be replaced.') from error
        return True
    finally:
        bridge.unref(doc)


def main():
    try:
        operation, source, *target = sys.argv[1:]
        if operation not in ('save', 'notes') or len(target) != (operation == 'save'):
            raise ValueError('Invalid annotation request.')
        data = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(data) > MAX_REQUEST:
            raise ValueError('Too many annotations in one request.')
        result = execute(operation, source, json.loads(data), *target)
        print(json.dumps({'result': result}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)[:600]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
