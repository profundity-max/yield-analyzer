import { Database, LogOut, Settings, ShieldCheck } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'

export function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark">DT</div>
          <div>
            <strong>AIM D-T</strong>
            <span>数据分析工作台</span>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>
            <Database size={18} /> 分析中心
          </NavLink>
          {user.role === 'admin' && (
            <NavLink to="/admin">
              <Settings size={18} /> 规则与管理
            </NavLink>
          )}
        </nav>
        <div className="sidebar-foot">
          <div className="user-chip">
            <ShieldCheck size={16} />
            <div>
              <strong>{user.username}</strong>
              <span>{user.role}</span>
            </div>
          </div>
          <button className="icon-button" title="退出登录" onClick={() => void logout()}>
            <LogOut size={18} />
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
