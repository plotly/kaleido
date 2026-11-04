/* global Plotly:false */

const semver = require('semver')
const cst = require('./constants')
const parse = require('./parse')

/**
 * @param {object} info : info object
 *  - data
 *  - format
 *  - width
 *  - height
 *  - scale
 *  - encoded
 * @param {string} mapboxAccessToken: mapboxAccessToken
 * @param {string} topojsonURL
 */
function render (info, topojsonURL, stepper) {
  let opts = {};

  if (topojsonURL != undefined && topojsonURL.length > 0) {
    opts.topojsonURL = topojsonURL;
  }

  // Rename info.data to info.figure
  info.figure = info.data
  delete info.data;

  // Parse request
  let parsed = parse(info, opts);
  if (parsed.code !== 0) {
    // Bad request return promise with error info
    return new Promise((resolve) => {resolve(parsed)})
  }

  // Use parsed export request
  info = parsed.result;
  const figure = info.figure;
  const format = info.format;
  const encoded = info.encoded;
  const fonts = info.fonts || [];

  // Build default config, and let figure.config override it
  const defaultConfig = {
    mapboxAccessToken: opts.mapboxAccessToken || null,
    plotGlPixelRatio: info.scale * 2
  }
  if (opts.topojsonURL) {
    defaultConfig.topojsonURL = opts.topojsonURL
  }

  const config = Object.assign(defaultConfig, figure.config)

  let errorCode = 0
  let result = null
  let errorMsg = null
  let pdfBgColor = null
  const done = () => {
    if (errorCode !== 0 && !errorMsg) {
      errorMsg = cst.statusMsg[errorCode]
    }

    return {
      code: errorCode,
      message: errorMsg,
      pdfBgColor,
      format,
      result,
      width: info.width,
      height: info.height,
      scale: info.scale,
    }
  }

  const PRINT_TO_PDF = (format === 'pdf' || format === 'eps')
  const PRINT_TO_EMF = (format === 'emf')

  let imgOptsFormat
  if (PRINT_TO_PDF || PRINT_TO_EMF) {
    imgOptsFormat = 'svg'
  } else if (format === 'json') {
    imgOptsFormat = 'full-json'
  } else {
    imgOptsFormat = format
  }

  // stash `paper_bgcolor` here in order to set the pdf window bg color
  const pdfBackground = (gd, _bgColor) => {
    if (!pdfBgColor) pdfBgColor = _bgColor
    gd._fullLayout.paper_bgcolor = 'rgba(0,0,0,0)'
  }

  const imgOpts = {
    format: imgOptsFormat,
    width: info.width,
    height: info.height,
    // only works as of plotly.js v1.31.0
    scale: info.scale,
    // return image data w/o the leading 'data:image' spec
    imageDataOnly: PRINT_TO_EMF || (!PRINT_TO_PDF && !encoded),
    // blend (emf|jpeg) background color as (emf|jpeg) does not support transparency
    setBackground: (format === 'jpeg' || format === 'emf') ? 'opaque'
      : PRINT_TO_PDF ? pdfBackground
        : ''
  }

  if (
    // 'full-json' was introduced in plotly.js v1.53.0
    // see: https://github.com/plotly/plotly.js/releases/tag/v1.53.0
    imgOpts.format === 'full-json' && semver.lt(Plotly.version, '1.53.0')
  ) {
    errorCode = 527
    errorMsg = `plotly.js version: ${Plotly.version}`
    return new Promise((resolve) => {resolve(done())})
  }

  if (semver.lt(Plotly.version, '1.11.0')) {
    errorCode = 526
    errorMsg = `plotly.js version: ${Plotly.version}`
    return new Promise((resolve) => {resolve(done())})
  }

  // Render the figure to an image. Wrapped in a function so it only runs
  // *after* any custom fonts have loaded (see loadFonts below), ensuring text
  // is measured with the correct font metrics.
  const makeImage = () => {
    if (semver.gte(Plotly.version, '1.30.0')) {
      return Plotly
        .toImage({ data: figure.data, layout: figure.layout, config: config }, imgOpts)
    }

    const gd = document.createElement('div')
    return Plotly
      .newPlot(gd, figure.data, figure.layout, config)
      .then(() => Plotly.toImage(gd, imgOpts))
      .then((imgData) => {
        Plotly.purge(gd)

        switch (format) {
          case 'png':
          case 'jpeg':
          case 'webp':
            if (encoded) {
              return imgData
            } else {
              return imgData.replace(cst.imgPrefix.base64, '')
            }
          case 'svg':
            if (encoded) {
              return imgData
            } else {
              return decodeSVG(response.result)
            }
          case 'pdf':
          case 'eps':
          case 'emf':
            return imgData
        }
      })
  }

  // Load any custom fonts into the page before rendering. This both fixes text
  // measurement and lets the (now embedded) @font-face survive into vector
  // output. No-op when no fonts were requested.
  const promise = loadFonts(fonts).then(makeImage)

  const img = document.getElementById("kaleido-image")
  const style = document.getElementById("head-style")

  let exportPromise = promise.then((imgData) => {
    // For vector output, inline the fonts into the SVG itself so the result is
    // self-contained and renders correctly without the font being installed.
    if (fonts.length && (format === 'svg' || PRINT_TO_PDF)) {
      imgData = injectFontsIntoSVG(imgData, fonts)
    }
    result = imgData
    return done()
  })

  if (PRINT_TO_PDF || stepper) {
    exportPromise = exportPromise.then((response) => {
      // Retrun promise that resolves when the image is loaded in the <img> element
      return new Promise((resolve, reject) => {
        prefix = ""
        switch (format) {
          case 'png':
          case 'jpeg':
          case 'webp':
            if (!encoded) {
              prefix = `data:image/${format};base64,`
            }
            break;
          case 'svg':
            resolve(response, null)
        }

        style.innerHTML = `
        @page { size: ${info.width * info.scale}px ${info.height * info.scale}px; }
        body { margin: 0; padding: 0; background-color: ${pdfBgColor} }
        `

        img.onload = img.onerror = resolve.bind(null, response)
        if (PRINT_TO_PDF) {
          img.onerror = reject
        }

        img.src = prefix + response.result

        setTimeout(() => reject(new Error('too long to load image')), cst.pdfPageLoadImgTimeout)
      }).then((response, e) => {
        // We don't need to transport image bytes back to C++ since PDF export will be performed
        if (PRINT_TO_PDF) {
          result = null
          return done()
        } else {
          return response
        }
      })
    })
  }

  return exportPromise
      .catch((err) => {
        console.log(err)
        errorCode = 525
        errorMsg = err.message
        result = null;
        return done()
      })
}

function decodeSVG (imgData) {
  return window.decodeURIComponent(imgData.replace(cst.imgPrefix.svg, ''))
}

/**
 * Register custom fonts with the page and wait for them to be ready.
 *
 * @param {Array<{family: string, format: string, url: string}>} fonts
 * @return {Promise} resolves once every font has loaded (failures are logged,
 *   not fatal, so rendering still proceeds with a fallback).
 */
function loadFonts (fonts) {
  if (!fonts || !fonts.length ||
      typeof FontFace === 'undefined' || !document.fonts) {
    return Promise.resolve()
  }

  return Promise.all(fonts.map((font) => {
    const face = new FontFace(font.family, `url(${font.url})`)
    document.fonts.add(face)
    return face.load().catch((err) => {
      console.log(`kaleido: failed to load font '${font.family}': ${err}`)
    })
  })).then(() => document.fonts.ready)
}

/**
 * Inline @font-face rules (with base64 font data) into an SVG so the vector
 * output embeds the fonts and renders identically anywhere, with no system
 * font installation required.
 *
 * @param {string} imgData : either a raw SVG string or a
 *   `data:image/svg+xml,...` URI (handled transparently).
 * @param {Array<{family: string, format: string, url: string}>} fonts
 * @return {string} imgData in the same form it was passed in.
 */
function injectFontsIntoSVG (imgData, fonts) {
  if (!fonts || !fonts.length) return imgData

  const css = fonts.map((font) =>
    `@font-face { font-family: '${font.family}';` +
    ` src: url(${font.url}) format('${font.format}'); }`
  ).join('\n')
  const styleEl = `<style type="text/css"><![CDATA[\n${css}\n]]></style>`

  const isDataUri = imgData.indexOf('data:image/svg+xml,') === 0
  let svg = isDataUri
    ? window.decodeURIComponent(imgData.replace(cst.imgPrefix.svg, ''))
    : imgData

  // Insert the <style> block immediately after the opening <svg ...> tag.
  svg = svg.replace(/(<svg\b[^>]*>)/, `$1${styleEl}`)

  return isDataUri
    ? 'data:image/svg+xml,' + window.encodeURIComponent(svg)
    : svg
}

module.exports = render
