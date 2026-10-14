import { ArrowLeft } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { AnalysisWorkspace } from '../components/AnalysisWorkspace'

export function AnalysisPage() {
  const { analysisId = '' } = useParams()
  return (
    <div className="page">
      <header className="page-header analysis-header">
        <div>
          <Link className="back-link" to="/"><ArrowLeft size={16} /> 返回分析中心</Link>
          <h1>分析结果</h1>
          <p>Spec、启用的测试点和设备 Mapping 可以在这里直接调整并重新生成结果。</p>
        </div>
      </header>
      <AnalysisWorkspace analysisId={analysisId} />
    </div>
  )
}
