import { useCallback, useState } from 'react'
import { downloadExport } from '../../api/client.js'
import {
  deleteMeasurement,
  exportMeasurementsUrl,
  listMeasurements
} from '../../api/measurements.js'
import ConfirmDialog from '../../components/common/ConfirmDialog.jsx'
import Pagination from '../../components/common/Pagination.jsx'
import { SectionCard } from '../../components/common/Card.jsx'
import { Alert } from '../../components/common/Feedback.jsx'
import { useToast } from '../../components/common/ToastProvider.jsx'
import { useListQuery } from '../../hooks/useListQuery.js'
import { saveBlob } from '../../utils/download.js'
import EntryForm from './components/EntryForm.jsx'
import EntryResultPanel from './components/EntryResultPanel.jsx'
import MeasurementFilters from './components/MeasurementFilters.jsx'
import MeasurementTable from './components/MeasurementTable.jsx'

const INITIAL_FILTERS = {
  station_id: '',
  pollutant: '',
  period: '',
  is_exceeded: '',
  date_from: '',
  date_to: ''
}

export default function MeasurementsPage() {
  const toast = useToast()
  const query = useListQuery(listMeasurements, INITIAL_FILTERS)
  const [result, setResult] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const handleSubmitted = useCallback(
    (payload) => {
      setResult({ kind: 'submit', payload })
      // 新录入的数据可能改变排序结果, 回第一页重建快照
      query.refresh()
    },
    [query]
  )

  const handleDelete = useCallback(async () => {
    if (!pendingDelete) return
    setDeleting(true)
    try {
      await deleteMeasurement(pendingDelete.id)
      toast.success('监测数据已删除')
      setPendingDelete(null)
      query.refresh()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setDeleting(false)
    }
  }, [pendingDelete, query, toast])

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const params = { ...query.filters, sort: query.sort, order: query.order }
      const blob = await downloadExport(
        (useToken) =>
          exportMeasurementsUrl({ ...params, ...(useToken ? { snapshot_token: useToken } : {}) }),
        query.data?.snapshot_token
      )
      saveBlob(blob, `监测数据_${Date.now()}.csv`)
      toast.success(`导出完成, 共 ${query.total} 条`)
    } catch (error) {
      toast.error(error.message)
    } finally {
      setExporting(false)
    }
  }, [query.filters, query.sort, query.order, query.total, query.data, toast])

  return (
    <>
      <div className="grid-2">
        <EntryForm
          onPreview={(payload) => setResult({ kind: 'preview', payload })}
          onSubmitted={handleSubmitted}
        />
        <EntryResultPanel result={result} summary={query.summary} onClose={() => setResult(null)} />
      </div>

      <MeasurementFilters
        value={query.filters}
        loading={query.loading}
        onSubmit={(next) => query.setFilters(next)}
        onReset={() => query.setFilters(INITIAL_FILTERS)}
      />

      {query.error ? <Alert tone="error">{query.error.message}</Alert> : null}

      <SectionCard
        title="最近录入的数据"
        hint="按监测时间倒序展示, 便于核对刚提交的记录"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={query.refresh} disabled={query.loading}>
              刷新
            </button>
            <button type="button" className="btn btn-sm btn-primary" onClick={handleExport} disabled={exporting}>
              {exporting ? '导出中...' : '导出 CSV'}
            </button>
          </>
        }
      >
        <MeasurementTable
          rows={query.items}
          loading={query.loading}
          onDelete={(row) => setPendingDelete(row)}
        />
        <Pagination
          page={query.page}
          pages={query.pages}
          total={query.total}
          pageSize={query.pageSize}
          onPageChange={query.setPage}
          onPageSizeChange={query.setPageSize}
        />
      </SectionCard>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        danger
        busy={deleting}
        title="删除监测数据"
        message={`确认删除 ${pendingDelete?.pollutant_label || ''} 的这条记录吗?`}
        detail="若该记录已产生超标记录, 对应的标注信息也会一并删除。"
        confirmText="确认删除"
        onConfirm={handleDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  )
}
