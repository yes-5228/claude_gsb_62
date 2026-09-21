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

export function downloadFile(url) {
  return axios
    .get(url, { baseURL, responseType: 'blob' })
    .then((response) => response.data)
}

/**
 * 下载导出文件: 当携带的结果集快照令牌已过期 (410) 时, 丢弃令牌按最新
 * 数据重试一次。`buildUrl(includeSnapshot)` 返回请求地址。
 */
export async function downloadExport(buildUrl, snapshotToken) {
  try {
    return await downloadFile(buildUrl(snapshotToken))
  } catch (error) {
    if (error.response?.status === 410 && snapshotToken) {
      return downloadFile(buildUrl(null))
    }
    throw error
  }
}

export default http
