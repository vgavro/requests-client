from lxml import html, etree

# TODO: xml support (not only html), FindError on attrib lookup


class FindError(ValueError):
    def __init__(self, msg, element, expr=None):
        self.msg = msg
        self.element = element
        self.expr = expr
        super().__init__(msg, element)

    def __str__(self):
        return '%s\n%s' % (
            (self.expr and '%s expr=%s' % (self.msg, self.expr) or self.msg),
            # TODO: this will produce too much noise, so add full=False
            # and shorten element representation
            etree.tostring(self.element, pretty_print=True).decode()
        )


class FindMixin:
    def xpath_one(self, expr, *args, **kwargs):
        rv = self.xpath_or_error(expr, *args, **kwargs)
        if len(rv) > 1:
            raise FindError('Expected xpath single match, got %s' % len(rv), self, expr)
        return rv[0]

    def xpath_first(self, *args, **kwargs):
        return self.xpath_or_error(*args, **kwargs)[0]

    def xpath_or_error(self, expr, *args, **kwargs):
        rv = self.xpath(expr, *args, **kwargs)
        if not len(rv):
            raise FindError('Expected xpath match', self, expr)
        return rv


class CssFindMixin:
    def cssselect_one(self, expr, *args, **kwargs):
        rv = self.cssselect_or_error(expr, *args, **kwargs)
        if len(rv) > 1:
            raise FindError('Expected cssselect single match, got %s' % len(rv), self, expr)
        return rv[0]

    def cssselect_first(self, *args, **kwargs):
        return self.cssselect_or_error(*args, **kwargs)[0]

    def cssselect_or_error(self, expr, *args, **kwargs):
        rv = self.cssselect(expr, *args, **kwargs)
        if not len(rv):
            raise FindError('Expected cssselect match', self, expr)
        return rv


class HtmlElement(FindMixin, CssFindMixin, html.HtmlElement):
    pass


class HtmlElementClassLookup(html.HtmlElementClassLookup):
    def __init__(self, classes=None, mixins=None):
        if not mixins:
            mixins = [('*', FindMixin), ('*', CssFindMixin)]
        super().__init__(classes, mixins)

    def lookup(self, node_type, document, namespace, name):
        if node_type == 'element':
            # Override default as it's not using mixin
            return self._element_classes.get(name.lower(), HtmlElement)
        return super().lookup(node_type, document, namespace, name)


class HTMLParser(etree.HTMLParser):
    # Copy of lxml.html.HTMLParser with custom lookup
    def __init__(self, **kwargs):
        super(HTMLParser, self).__init__(**kwargs)
        self.set_element_class_lookup(HtmlElementClassLookup())


class XHTMLParser(etree.XMLParser):
    # Copy of lxml.html.XHTMLParser with custom lookup
    def __init__(self, **kwargs):
        super(XHTMLParser, self).__init__(**kwargs)
        self.set_element_class_lookup(HtmlElementClassLookup())


def html_from_response(resp, **kwargs):
    # Expected requests Response object
    return html.fromstring(resp.text, base_url=resp.url, parser=html_parser, **kwargs)


def html_from_string(string, **kwargs):
    return html.fromstring(string, parser=html_parser, **kwargs)


html_parser = HTMLParser()
xhtml_parser = XHTMLParser()
