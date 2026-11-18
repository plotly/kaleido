const cst = require('./constants')
const isPlainObj = require('is-plain-obj')
const isPositiveNumeric = require('./is-positive-numeric')
const isNonEmptyString = require('./is-non-empty-string')

const contentFormat = cst.contentFormat
const ACCEPT_HEADER = Object.keys(contentFormat).reduce(function (obj, key) {
  obj[ contentFormat[key] ] = key
  return obj
}, {})

/** plotly-graph parse
 *
 * @param {object} body : JSON-parsed request body
 *  - figure
 *  - format
 *  - scale (only for plotly.js v.1.31.0 and up)
 *  - width
 *  - height
 *  - encoded
 *  - fid (figure id)
 * 0r:
 *  - data
 *  - layout
 * @param {object} _opts : component options
 *  - format
 *  - scale (only for plotly.js v.1.31.0 and up)
 *  - width
 *  - height
 *  - safeMode
 * @return {object}
 *  - errorCode
 *  - result
 */
function parse (body, _opts) {
  let debugStruct = {};
  const result = {}

  const errorOut = (code, extra) => {
    let message = `${cst.statusMsg[code]}`
    if (extra) message = `${message} (${extra})`
    return {code, message, result: null}
  }

  let figure
  let opts

  // to support both 'serve' requests (figure/format/../)
  // and 'run' body (data/layout) structures
  if (body.figure) {
    debugStruct['request_type'] = 'serve'
    figure = body.figure
    opts = body
  } else {
    debugStruct['request_type'] = 'run'
    figure = body
    opts = _opts
  }
  
  result.scale = isPositiveNumeric(opts.scale) ? Number(opts.scale) : cst.dflt.scale
  result.fid = isNonEmptyString(opts.fid) ? opts.fid : null
  result.encoded = !!opts.encoded
  result.fonts = Array.isArray(opts.fonts) ? opts.fonts : []

  if (isNonEmptyString(opts.format)) {
    if (cst.contentFormat[opts.format]) {
      result.format = opts.format
    } else {
      return errorOut(400, 'wrong format')
    }
  } else {
    result.format = cst.dflt.format;
  }

  if (!isPlainObj(figure)) {
    return errorOut(400, 'non-object figure: ' + JSON.stringify(debugStruct))
  }

  if (!figure.data && !figure.layout) {
    return errorOut(400, 'no \'data\' and no \'layout\' in figure')
  }

  result.figure = {}

  if ('data' in figure) {
    if (Array.isArray(figure.data)) {
      result.figure.data = figure.data
    } else {
      return errorOut(400, 'non-array figure data')
    }
  } else {
    result.figure.data = []
  }

  if ('layout' in figure) {
    if (isPlainObj(figure.layout)) {
      result.figure.layout = figure.layout
    } else {
      return errorOut(400, 'non-object figure layout')
    }
  } else {
    result.figure.layout = {}
  }

  result.width = parseDim(result, opts, 'width')
  result.height = parseDim(result, opts, 'height')

  if (_opts.safeMode && willFigureHang(result)) {
    return errorOut(400, 'figure data is likely to make exporter hang, rejecting request')
  }

  return {code: 0, message: null, result}
}

function parseDim (result, opts, dim) {
  const layout = result.figure.layout

  if (isPositiveNumeric(opts[dim])) {
    return Number(opts[dim])
  } else if (isPositiveNumeric(layout[dim]) && !layout.autosize) {
    return Number(layout[dim])
  } else {
    return cst.dflt[dim]
  }
}

function willFigureHang (result) {
  const data = result.figure.data

  // cap the number of traces
  if (data.length > 200) return true

  let maxPtBudget = 0

  for (let i = 0; i < data.length; i++) {
    const trace = data[i] || {}

    // cap the number of points using a budget
    maxPtBudget += estimateDataLength(trace) / maxPtsPerTrace(trace)
    if (maxPtBudget > 1) return true
  }
}

// Consider the array of maximum length as a proxy to determine
// the number of points to be drawn. In general, this estimate
// can be (much) smaller than the true number of points plotted
// when it does not match the length of the other coordinate arrays.
function findMaxArrayLength (cont) {
  const arrays = Object.keys(cont)
    .filter(k => Array.isArray(cont[k]))
    .map(k => cont[k])

  const lengths = arrays.map(arr => {
    if (Array.isArray(arr[0])) {
      // 2D array case
      return arr.reduce((a, r) => a + r.length, 0)
    } else {
      return arr.length
    }
  })

  return Math.max(0, ...lengths)
}

function estimateDataLength (trace) {
  const topLevel = findMaxArrayLength(trace)
  let dimLevel = 0
  let cellLevel = 0

  // special case for e.g. parcoords and splom traces
  if (Array.isArray(trace.dimensions)) {
    dimLevel = trace.dimensions
      .map(findMaxArrayLength)
      .reduce((a, v) => a + v)
  }

  // special case for e.g. table traces
  if (isPlainObj(trace.cells)) {
    cellLevel = findMaxArrayLength(trace.cells)
  }

  return Math.max(topLevel, dimLevel, cellLevel)
}

function maxPtsPerTrace (trace) {
  const type = trace.type || 'scatter'

  switch (type) {
    case 'scattergl':
    case 'splom':
    case 'pointcloud':
    case 'table':
      return 1e7

    case 'scatterpolargl':
    case 'heatmap':
    case 'heatmapgl':
      return 1e6

    case 'scatter3d':
    case 'surface':
      return 5e5

    case 'mesh3d':
      if ('alphahull' in trace && Number(trace.alphahull) >= 0) {
        return 1000
      } else {
        return 5e5
      }

    case 'parcoords':
      return 5e5
    case 'scattermapbox':
      return 5e5

    case 'histogram':
    case 'histogram2d':
    case 'histogram2dcontour':
      return 1e6

    case 'box':
      if (trace.boxpoints === 'all') {
        return 5e4
      } else {
        return 1e6
      }
    case 'violin':
      if (trace.points === 'all') {
        return 5e4
      } else {
        return 1e6
      }

    default:
      return 5e4
  }
}

module.exports = parse
