import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE || '/api'

export class ApiError extends Error {
  constructor(message, { status, fields, code } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields || {}
    this.code = code
  }
}

const http = axios.create({ baseURL, timeout: 20000 })

http.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const payload = error.response?.data?.error
    if (payload) {
      return Promise.reject(
        new ApiError(payload.message || '请求失败', {
          status: error.response.status,
          fields: payload.fields,
          code: payload.code
        })
      )
    }
    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new ApiError('请求超时, 请稍后重试'))
    }
    return Promise.reject(
      new ApiError(error.message === 'Network Error' ? '无法连接后端服务' : error.message)
    )
  }
)

/** Convert a filter object into request params, dropping empty values. */
export function toParams(filters = {}) {
  const params = {}
  Object.entries(filters).forEach(([key, value]) => {
    if (value === '' || value === null || value === undefined) return
    if (Array.isArray(value)) {
      if (value.length === 0) return
      params[key] = value.join(',')
      return
    }
    if (typeof value === 'boolean') {
      params[key] = value ? 'true' : 'false'
      return
    }
    params[key] = value
  })
  return params
}

export async function downloadFile(url) {
  const response = await axios.get(url, { baseURL, responseType: 'blob' })
  // The backend streams the exact filtered rows and echoes how many data
  // rows were written, so the UI can reconcile export count with the total.
  const count = Number(response.headers['x-result-count'])
  return { blob: response.data, count: Number.isFinite(count) ? count : null }
}

export default http
