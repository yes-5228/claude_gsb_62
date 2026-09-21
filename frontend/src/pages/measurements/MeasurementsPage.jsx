import { useCallback, useState } from 'react'
import { downloadFile } from '../../api/client.js'
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
  const query = useListQuery(listMeasurements, INITIAL_FILTERS, { mode: 'cursor' })
  const [result, setResult] = useState(null)
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)

  const handleSubmitted = useCallback(
    (payload) => {
      setResult({ kind: 'submit', payload })
      // Restart at page 1 so the just-recorded row and the new total show.
      query.reload()
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
      query.reload()
    } catch (error) {
      toast.error(error.message)
    } finally {
      setDeleting(false)
    }
  }, [pendingDelete, query, toast])

  const handleExport = useCallback(async () => {
    setExporting(true)
    try {
      const { blob, count } = await downloadFile(exportMeasurementsUrl(query.filters))
      saveBlob(blob, `监测数据_${Date.now()}.csv`)
      // Reconcile the streamed row count with the total above the list.
      if (count !== null && count !== query.total) {
        toast.warning(`导出 ${count} 条, 与列表总数 ${query.total} 条不一致, 数据可能刚被更新, 建议刷新后重试`)
      } else {
        toast.success(`导出任务已完成, 共 ${count ?? ''} 条, 与汇总条数一致`)
      }
    } catch (error) {
      toast.error(error.message)
    } finally {
      setExporting(false)
    }
  }, [query.filters, query.total, toast])

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
        hint="点击表头可排序; 翻页采用稳定游标, 他人录入/删除不会让已看过的页错位"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={query.reload} disabled={query.loading}>
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
          sort={query.sort}
          order={query.order}
          onSort={query.setSort}
          onDelete={(row) => setPendingDelete(row)}
        />
        <Pagination
          page={query.page}
          pages={query.pages}
          total={query.total}
          pageSize={query.pageSize}
          loading={query.loading}
          hasPrev={query.hasPrev}
          hasNext={query.hasNext}
          onFirst={query.goFirst}
          onPrev={query.goPrev}
          onNext={query.goNext}
          onLast={query.goLast}
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
