#!/usr/bin/python
# -*- coding: utf-8 -*-

# trml2pdf - An RML to PDF converter
# Copyright (C) 2003, Fabien Pinckaers, UCL, FSA
# Contributors
#     Richard Waid <richard@iopen.net>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import sys
import StringIO
import xml.dom.minidom
import copy

import reportlab
from reportlab.pdfgen import canvas
from reportlab import platypus
try:
	from reportlab.graphics.barcode.common import Codabar, Code11, I2of5, MSI
	from reportlab.graphics.barcode.code128 import Code128
	from reportlab.graphics.barcode.code39 import Standard39, Extended39
	from reportlab.graphics.barcode.code93 import Standard93, Extended93
	from reportlab.graphics.barcode.usps import FIM, POSTNET
	barcode_codes = dict(codabar=Codabar, code11=Code11, code128=Code128,
			     standard39=Standard39, extended39=Extended39, 
			     standard93=Standard93, extended93=Extended93,
			     i2of5=I2of5, msi=MSI, fim=FIM, postnet=POSTNET)
except ImportError:
	barcode_codes = {}
	pass

import utils
import color

#
# Change this to UTF-8 if you plan tu use Reportlab's UTF-8 support
#
encoding = 'latin1'

def _child_get(node, childs):
	clds = []
	for n in node.childNodes:
		if (n.nodeType==n.ELEMENT_NODE) and (n.localName==childs):
			clds.append(n)
	return clds

class _rml_styles(object):
	def __init__(self, nodes):
		self.styles = {}
		self.names = {}
		self.table_styles = {}
		for node in nodes:
			for style in node.getElementsByTagName('blockTableStyle'):
				self.table_styles[style.getAttribute('id')] = self._table_style_get(style)
			for style in node.getElementsByTagName('paraStyle'):
				self.styles[style.getAttribute('name')] = self._para_style_get(style)
			for variable in node.getElementsByTagName('initialize'):
				for name in variable.getElementsByTagName('name'):
					self.names[ name.getAttribute('id')] = name.getAttribute('value')

	def _para_style_update(self, style, node):
		for attr in ['textColor', 'backColor', 'bulletColor']:
			if node.hasAttribute(attr):
				style.__dict__[attr] = color.get(node.getAttribute(attr))
		for attr in ['fontName', 'bulletFontName', 'bulletText', 'wordWrap']:
			if node.hasAttribute(attr):
				style.__dict__[attr] = node.getAttribute(attr)
		for attr in ['fontSize', 'leftIndent', 'rightIndent', 'spaceBefore', 'spaceAfter', 'firstLineIndent', 'bulletIndent', 'bulletFontSize', 'leading']:
			if node.hasAttribute(attr):
				style.__dict__[attr] = utils.unit_get(node.getAttribute(attr))
		if node.hasAttribute('alignment'):
			align = {
				'right':reportlab.lib.enums.TA_RIGHT,
				'center':reportlab.lib.enums.TA_CENTER,
				'justify':reportlab.lib.enums.TA_JUSTIFY
			}
			style.alignment = align.get(node.getAttribute('alignment').lower(), reportlab.lib.enums.TA_LEFT)
		return style

	def _table_style_get(self, style_node):
		styles = []
		for node in style_node.childNodes:
			if node.nodeType==node.ELEMENT_NODE:
				start = utils.tuple_int_get(node, 'start', (0,0) )
				stop = utils.tuple_int_get(node, 'stop', (-1,-1) )
				if node.localName=='blockValign':
					styles.append(('VALIGN', start, stop, str(node.getAttribute('value'))))
				elif node.localName=='blockFont':
					styles.append(('FONT', start, stop, str(node.getAttribute('name'))))
				elif node.localName=='blockTextColor':
					styles.append(('TEXTCOLOR', start, stop, color.get(str(node.getAttribute('colorName')))))
				elif node.localName=='blockLeading':
					styles.append(('LEADING', start, stop, utils.unit_get(node.getAttribute('length'))))
				elif node.localName=='blockAlignment':
					styles.append(('ALIGNMENT', start, stop, str(node.getAttribute('value'))))
				elif node.localName=='blockLeftPadding':
					styles.append(('LEFTPADDING', start, stop, utils.unit_get(node.getAttribute('length'))))
				elif node.localName=='blockRightPadding':
					styles.append(('RIGHTPADDING', start, stop, utils.unit_get(node.getAttribute('length'))))
				elif node.localName=='blockTopPadding':
					styles.append(('TOPPADDING', start, stop, utils.unit_get(node.getAttribute('length'))))
				elif node.localName=='blockBottomPadding':
					styles.append(('BOTTOMPADDING', start, stop, utils.unit_get(node.getAttribute('length'))))
				elif node.localName=='blockBackground':
					styles.append(('BACKGROUND', start, stop, color.get(node.getAttribute('colorName'))))
				elif node.localName=='blockSpan':
					styles.append(('SPAN', start, stop))
				if node.hasAttribute('size'):
					styles.append(('FONTSIZE', start, stop, utils.unit_get(node.getAttribute('size'))))
				elif node.localName=='lineStyle':
					kind = node.getAttribute('kind')
					kind_list = [ 'GRID', 'BOX', 'OUTLINE', 'INNERGRID', 'LINEBELOW', 'LINEABOVE','LINEBEFORE', 'LINEAFTER' ]
					assert kind in kind_list
					thick = 1
					if node.hasAttribute('thickness'):
						thick = float(node.getAttribute('thickness'))
					styles.append((kind, start, stop, thick,  color.get(node.getAttribute('colorName'))))
		return platypus.tables.TableStyle(styles)

	def _para_style_get(self, node):
		styles = reportlab.lib.styles.getSampleStyleSheet()
		style = copy.deepcopy(styles["Normal"])
		self._para_style_update(style, node)
		return style

	def para_style_get(self, node):
		style = False
		if node.hasAttribute('style'):
			if node.getAttribute('style') in self.styles:
				style = copy.deepcopy(self.styles[node.getAttribute('style')])
			else:
				sys.stderr.write('Warning: style not found, %s - setting default!\n' % (node.getAttribute('style'),) )
		if not style:
			styles = reportlab.lib.styles.getSampleStyleSheet()
			style = copy.deepcopy(styles['Normal'])
		return self._para_style_update(style, node)

class _rml_doc(object):
	def __init__(self, data):
		self.dom = xml.dom.minidom.parseString(data)
		self.filename = self.dom.documentElement.getAttribute('filename')

	def docinit(self, els):
		from reportlab.lib.fonts import addMapping
		from reportlab.pdfbase import pdfmetrics
		from reportlab.pdfbase.ttfonts import TTFont

		for node in els:
			for font in node.getElementsByTagName('registerFont'):
				name = font.getAttribute('fontName').encode('ascii')
				fname = font.getAttribute('fontFile').encode('ascii')
				pdfmetrics.registerFont(TTFont(name, fname ))
				addMapping(name, 0, 0, name)    #normal
				addMapping(name, 0, 1, name)    #italic
				addMapping(name, 1, 0, name)    #bold
				addMapping(name, 1, 1, name)    #italic and bold

	def render(self, out):
		el = self.dom.documentElement.getElementsByTagName('docinit')
		if el:
			self.docinit(el)

		el = self.dom.documentElement.getElementsByTagName('stylesheet')
		self.styles = _rml_styles(el)

		el = self.dom.documentElement.getElementsByTagName('template')
		if len(el):
			pt_obj = _rml_template(out, el[0], self)
			pt_obj.render(self.dom.documentElement.getElementsByTagName('story')[0])
		else:
			self.canvas = canvas.Canvas(out)
			pd = self.dom.documentElement.getElementsByTagName('pageDrawing')[0]
			pd_obj = _rml_canvas(self.canvas, None, self)
			pd_obj.render(pd)
			self.canvas.showPage()
			self.canvas.save()

class _rml_canvas(object):
	def __init__(self, canvas, doc_tmpl=None, doc=None):
		self.canvas = canvas
		self.styles = doc.styles
		self.doc_tmpl = doc_tmpl
		self.doc = doc

	def _textual(self, node):
		rc = ''
		for n in node.childNodes:
			if n.nodeType == n.ELEMENT_NODE:
				if n.localName=='pageNumber':
					rc += str(self.canvas.getPageNumber())
			elif (n.nodeType == node.CDATA_SECTION_NODE):
				rc += n.data
			elif (n.nodeType == node.TEXT_NODE):
				rc += n.data
		return rc.encode(encoding)

	def _drawString(self, node):
		self.canvas.drawString(text=self._textual(node), **utils.attr_get(node, ['x','y']))
	def _drawCenteredString(self, node):
		self.canvas.drawCentredString(text=self._textual(node), **utils.attr_get(node, ['x','y']))
	def _drawRightString(self, node):
		self.canvas.drawRightString(text=self._textual(node), **utils.attr_get(node, ['x','y']))
	def _rect(self, node):
		if node.hasAttribute('round'):
			self.canvas.roundRect(radius=utils.unit_get(node.getAttribute('round')), **utils.attr_get(node, ['x','y','width','height'], {'fill':'bool','stroke':'bool'}))
		else:
			self.canvas.rect(**utils.attr_get(node, ['x','y','width','height'], {'fill':'bool','stroke':'bool'}))
	def _ellipse(self, node):
		x1 = utils.unit_get(node.getAttribute('x'))
		x2 = utils.unit_get(node.getAttribute('width'))
		y1 = utils.unit_get(node.getAttribute('y'))
		y2 = utils.unit_get(node.getAttribute('height'))
		self.canvas.ellipse(x1,y1,x2,y2, **utils.attr_get(node, [], {'fill':'bool','stroke':'bool'}))
	def _curves(self, node):
		line_str = utils.text_get(node).split()
		lines = []
		while len(line_str)>7:
			self.canvas.bezier(*[utils.unit_get(l) for l in line_str[0:8]])
			line_str = line_str[8:]
	def _lines(self, node):
		line_str = utils.text_get(node).split()
		lines = []
		while len(line_str)>3:
			lines.append([utils.unit_get(l) for l in line_str[0:4]])
			line_str = line_str[4:]
		self.canvas.lines(lines)
	def _grid(self, node):
		xlist = [utils.unit_get(s) for s in node.getAttribute('xs').split(',')]
		ylist = [utils.unit_get(s) for s in node.getAttribute('ys').split(',')]
		self.canvas.grid(xlist, ylist)
	def _translate(self, node):
		dx = 0
		dy = 0
		if node.hasAttribute('dx'):
			dx = utils.unit_get(node.getAttribute('dx'))
		if node.hasAttribute('dy'):
			dy = utils.unit_get(node.getAttribute('dy'))
		self.canvas.translate(dx,dy)

	def _circle(self, node):
		self.canvas.circle(x_cen=utils.unit_get(node.getAttribute('x')), y_cen=utils.unit_get(node.getAttribute('y')), r=utils.unit_get(node.getAttribute('radius')), **utils.attr_get(node, [], {'fill':'bool','stroke':'bool'}))

	def _place(self, node):
		flows = _rml_flowable(self.doc).render(node)
		infos = utils.attr_get(node, ['x','y','width','height'])

		infos['y']+=infos['height']
		for flow in flows:
			w,h = flow.wrap(infos['width'], infos['height'])
			if w<=infos['width'] and h<=infos['height']:
				infos['y']-=h
				flow.drawOn(self.canvas,infos['x'],infos['y'])
				infos['height']-=h
			else:
				raise ValueError, "Not enough space"

	def _line_mode(self, node):
		ljoin = {'round':1, 'mitered':0, 'bevelled':2}
		lcap = {'default':0, 'round':1, 'square':2}
		if node.hasAttribute('width'):
			self.canvas.setLineWidth(utils.unit_get(node.getAttribute('width')))
		if node.hasAttribute('join'):
			self.canvas.setLineJoin(ljoin[node.getAttribute('join')])
		if node.hasAttribute('cap'):
			self.canvas.setLineCap(lcap[node.getAttribute('cap')])
		if node.hasAttribute('miterLimit'):
			self.canvas.setDash(utils.unit_get(node.getAttribute('miterLimit')))
		if node.hasAttribute('dash'):
			dashes = node.getAttribute('dash').split(',')
			for x in range(len(dashes)):
				dashes[x]=utils.unit_get(dashes[x])
			self.canvas.setDash(node.getAttribute('dash').split(','))

	def _image(self, node):
		import urllib
		from reportlab.lib.utils import ImageReader
		u = urllib.urlopen(str(node.getAttribute('file')))
		s = StringIO.StringIO()
		s.write(u.read())
		s.seek(0)
		img = ImageReader(s)
		(sx,sy) = img.getSize()

		args = {}
		for tag in ('width','height','x','y'):
			if node.hasAttribute(tag):
				args[tag] = utils.unit_get(node.getAttribute(tag))
		if ('width' in args) and (not 'height' in args):
			args['height'] = sy * args['width'] / sx
		elif ('height' in args) and (not 'width' in args):
			args['width'] = sx * args['height'] / sy
		elif ('width' in args) and ('height' in args):
			if (float(args['width'])/args['height'])>(float(sx)>sy):
				args['width'] = sx * args['height'] / sy
			else:
				args['height'] = sy * args['width'] / sx
		self.canvas.drawImage(img, **args)

	def _path(self, node):
		self.path = self.canvas.beginPath()
		self.path.moveTo(**utils.attr_get(node, ['x','y']))
		for n in node.childNodes:
			if n.nodeType == node.ELEMENT_NODE:
				if n.localName=='moveto':
					vals = utils.text_get(n).split()
					self.path.moveTo(utils.unit_get(vals[0]), utils.unit_get(vals[1]))
				elif n.localName=='curvesto':
					vals = utils.text_get(n).split()
					while len(vals)>5:
						pos=[]
						while len(pos)<6:
							pos.append(utils.unit_get(vals.pop(0)))
						self.path.curveTo(*pos)
			elif (n.nodeType == node.TEXT_NODE):
				data = n.data.split()               # Not sure if I must merge all TEXT_NODE ?
				while len(data)>1:
					x = utils.unit_get(data.pop(0))
					y = utils.unit_get(data.pop(0))
					self.path.lineTo(x,y)
		if (not node.hasAttribute('close')) or utils.bool_get(node.getAttribute('close')):
			self.path.close()
		self.canvas.drawPath(self.path, **utils.attr_get(node, [], {'fill':'bool','stroke':'bool'}))

	def render(self, node):
		tags = {
			'drawCentredString': self._drawCenteredString,
			'drawRightString': self._drawRightString,
			'drawString': self._drawString,
			'rect': self._rect,
			'ellipse': self._ellipse,
			'lines': self._lines,
			'grid': self._grid,
			'curves': self._curves,
			'fill': lambda node: self.canvas.setFillColor(color.get(node.getAttribute('color'))),
			'stroke': lambda node: self.canvas.setStrokeColor(color.get(node.getAttribute('color'))),
			'setFont': lambda node: self.canvas.setFont(node.getAttribute('name'), utils.unit_get(node.getAttribute('size'))),
			'place': self._place,
			'circle': self._circle,
			'lineMode': self._line_mode,
			'path': self._path,
			'rotate': lambda node: self.canvas.rotate(float(node.getAttribute('degrees'))),
			'translate': self._translate,
			'image': self._image
		}
		for nd in node.childNodes:
			if nd.nodeType==nd.ELEMENT_NODE:
				for tag in tags:
					if nd.localName==tag:
						tags[tag](nd)
						break

class _rml_draw(object):
	def __init__(self, node, styles):
		self.node = node
		self.styles = styles
		self.canvas = None

	def render(self, canvas, doc):
		canvas.saveState()
		cnv = _rml_canvas(canvas, doc, self.styles)
		cnv.render(self.node)
		canvas.restoreState()

class _rml_flowable(object):
	def __init__(self, doc):
		self.doc = doc
		self.styles = doc.styles

	def _textual(self, node):
		rc = ''
		for n in node.childNodes:
			if n.nodeType == node.ELEMENT_NODE:
				if n.localName=='getName':
					newNode = self.doc.dom.createTextNode(self.styles.names.get(n.getAttribute('id'),'Unknown name'))
					node.insertBefore(newNode, n)
					node.removeChild(n)
				if n.localName=='pageNumber':
					rc+='<pageNumber/>'            # TODO: change this !
				else:
					self._textual(n)
				rc += n.toxml()
			elif (n.nodeType == node.CDATA_SECTION_NODE):
				rc += n.data
			elif (n.nodeType == node.TEXT_NODE):
				rc += n.data
		return rc.encode(encoding)

	_cell_cmds = {
		"align":"ALIGN",
		"vAlign":"VALIGN",
		"leftPadding":"LEFTPADDING",
		"rightPadding":"RIGHTPADDING",
		"topPadding":"TOPPADDING",
		"bottomPadding":"BOTTOMPADDING",
		"bottomPadding":"BOTTOMPADDING",
		"leading":"LEADING",
		"fontName":"FONTNAME",
		"fontSize":"FONTSIZE",
		"textColor":"TEXTCOLOR",
		"fontColor":"TEXTCOLOR",
	}

	def _get_cell_style(self, x, y, style, option):
		return tuple([self._cell_cmds[style], (x, y), (x, y), str(option)])

	def _table(self, node):
		length = 0
		colwidths = None
		rowheights = None
		data = []
		cell_styles=[]
		y = 0
		for tr in _child_get(node,'tr'):
			data2 = []
			x = 0
			for td in _child_get(tr, 'td'):
				flow = []
				for n in td.childNodes:
					if n.nodeType==node.ELEMENT_NODE:
						flow.append( self._flowable(n) )
				if not len(flow):
					flow = self._textual(td)
				data2.append( flow )
				for tag in self._cell_cmds.keys():
					if td.hasAttribute(tag):
						cell_styles.append(self._get_cell_style(
							x, y , tag, td.getAttribute(tag)))
				x += 1
			if len(data2)>length:
				length=len(data2)
				for ab in data:
					while len(ab)<length:
						ab.append('')
			while len(data2)<length:
				data2.append('')
			data.append( data2 )
			y += 1
		if node.hasAttribute('colWidths'):
			assert length == len(node.getAttribute('colWidths').split(','))
			colwidths = [utils.unit_get(f.strip()) for f in node.getAttribute('colWidths').split(',')]
		if node.hasAttribute('rowHeights'):
			rowheights = [utils.unit_get(f.strip()) for f in node.getAttribute('rowHeights').split(',')]
		table = platypus.Table(data = data, colWidths=colwidths, rowHeights=rowheights, **(utils.attr_get(node, ['splitByRow'] ,{'repeatRows':'int','repeatCols':'int'})))
		if node.hasAttribute('style'):
			table.setStyle(self.styles.table_styles[node.getAttribute('style')])
		if cell_styles:
			table.setStyle(platypus.tables.TableStyle(cell_styles))
		return table

	def _illustration(self, node):
		class Illustration(platypus.flowables.Flowable):
			def __init__(self, node, styles):
				self.node = node
				self.styles = styles
				self.width = utils.unit_get(node.getAttribute('width'))
				self.height = utils.unit_get(node.getAttribute('height'))
			def wrap(self, *args):
				return (self.width, self.height)
			def draw(self):
				canvas = self.canv
				drw = _rml_draw(self.node, self.styles)
				drw.render(self.canv, None)
		return Illustration(node, self.styles)

	def _flowable(self, node):
		if node.localName=='para':
			style = self.styles.para_style_get(node)
			return platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str'})))
		elif node.localName=='name':
			self.styles.names[ node.getAttribute('id')] = node.getAttribute('value')
			return None
		elif node.localName=='xpre':
			style = self.styles.para_style_get(node)
			return platypus.XPreformatted(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str','dedent':'int','frags':'int'})))
		elif node.localName=='pre':
			style = self.styles.para_style_get(node)
			return platypus.Preformatted(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str','dedent':'int'})))
		elif node.localName=='illustration':
			return  self._illustration(node)
		elif node.localName=='blockTable':
			return  self._table(node)
		elif node.localName=='title':
			styles = reportlab.lib.styles.getSampleStyleSheet()
			style = styles['Title']
			return platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str'})))
		elif node.localName=='h1':
			styles = reportlab.lib.styles.getSampleStyleSheet()
			style = styles['Heading1']
			return platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str'})))
		elif node.localName=='h2':
			styles = reportlab.lib.styles.getSampleStyleSheet()
			style = styles['Heading2']
			return platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str'})))
		elif node.localName=='h3':
			styles = reportlab.lib.styles.getSampleStyleSheet()
			style = styles['Heading3']
			return platypus.Paragraph(self._textual(node), style, **(utils.attr_get(node, [], {'bulletText':'str'})))
		elif node.localName=='image':
			return platypus.Image(node.getAttribute('file'), mask=(250,255,250,255,250,255), **(utils.attr_get(node, ['width','height'])))
		elif node.localName=='spacer':
			if node.hasAttribute('width'):
				width = utils.unit_get(node.getAttribute('width'))
			else:
				width = utils.unit_get('1cm')
			length = utils.unit_get(node.getAttribute('length'))
			return platypus.Spacer(width=width, height=length)
		elif node.localName=='pageBreak':
			return platypus.PageBreak()
		elif node.localName=='condPageBreak':
			return platypus.CondPageBreak(**(utils.attr_get(node, ['height'])))
		elif node.localName=='setNextTemplate':
			return platypus.NextPageTemplate(str(node.getAttribute('name')))
		elif node.localName=='nextFrame':
			return platypus.CondPageBreak(1000)           # TODO: change the 1000 !
		elif barcode_codes and node.localName=='barCode':
			code = barcode_codes.get(node.getAttribute('code'), Code128)
			return code(self._textual(node), **utils.attr_get(node, ['barWidth', 'barHeight']))
		else:
			sys.stderr.write('Warning: flowable not yet implemented: %s !\n' % (node.localName,))
			return None

	def render(self, node_story):
		story = []
		node = node_story.firstChild
		while node:
			if node.nodeType == node.ELEMENT_NODE:
				flow = self._flowable(node) 
				if flow:
					story.append(flow)
			node = node.nextSibling
		return story

class _rml_template(object):
	def __init__(self, out, node, doc):
		if not node.hasAttribute('pageSize'):
			pageSize = (utils.unit_get('21cm'), utils.unit_get('29.7cm'))
		else:
			ps = map(lambda x:x.strip(), node.getAttribute('pageSize').replace(')', '').replace('(', '').split(','))
			pageSize = ( utils.unit_get(ps[0]),utils.unit_get(ps[1]) )
		cm = reportlab.lib.units.cm
		self.doc_tmpl = platypus.BaseDocTemplate(out, pagesize=pageSize, **utils.attr_get(node, ['leftMargin','rightMargin','topMargin','bottomMargin'], {'allowSplitting':'int','showBoundary':'bool','title':'str','author':'str'}))
		self.page_templates = []
		self.styles = doc.styles
		self.doc = doc
		pts = node.getElementsByTagName('pageTemplate')
		for pt in pts:
			frames = []
			for frame_el in pt.getElementsByTagName('frame'):
				frame = platypus.Frame( **(utils.attr_get(frame_el, ['x1','y1', 'width','height', 'leftPadding', 'rightPadding', 'bottomPadding', 'topPadding'], {'id':'text', 'showBoundary':'bool'})) )
				frames.append( frame )
			gr = pt.getElementsByTagName('pageGraphics')
			if len(gr):
				drw = _rml_draw(gr[0], self.doc)
				self.page_templates.append( platypus.PageTemplate(frames=frames, onPage=drw.render, **utils.attr_get(pt, [], {'id':'str'}) ))
			else:
				self.page_templates.append( platypus.PageTemplate(frames=frames, **utils.attr_get(pt, [], {'id':'str'}) ))
		self.doc_tmpl.addPageTemplates(self.page_templates)

	def render(self, node_story):
		r = _rml_flowable(self.doc)
		fis = r.render(node_story)
		self.doc_tmpl.build(fis)

def parseString(data, fout=None):
	r = _rml_doc(data)
	if fout:
		fp = file(fout,'wb')
		r.render(fp)
		fp.close()
		return fout
	else:
		fp = StringIO.StringIO()
		r.render(fp)
		return fp.getvalue()

def trml2pdf_help():
	print 'Usage: trml2pdf input.rml >output.pdf'
	print 'Render the standard input (RML) and output a PDF file'
	sys.exit(0)

if __name__=="__main__":
	if len(sys.argv)>1:
		if sys.argv[1]=='--help':
			trml2pdf_help()
		print parseString(file(sys.argv[1], 'r').read()),
	else:
		print 'Usage: trml2pdf input.rml >output.pdf'
		print 'Try \'trml2pdf --help\' for more information.'
