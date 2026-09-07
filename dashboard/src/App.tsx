import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { LoadingState } from './components/Primitives'
import { DashboardProvider } from './state'

const Overview = lazy(() => import('./pages/Overview'))
const SpendPage = lazy(() => import('./pages/Spend'))
const RoutingPage = lazy(() => import('./pages/Routing'))
const EfficacyPage = lazy(() => import('./pages/Efficacy'))
const HealthPage = lazy(() => import('./pages/Health'))
const TasksPage = lazy(() => import('./pages/Tasks'))

export default function App() {
  return <DashboardProvider><Shell><Suspense fallback={<LoadingState label="Loading page"/>}><Routes>
    <Route path="/" element={<Overview/>}/><Route path="/spend" element={<SpendPage/>}/><Route path="/routing" element={<RoutingPage/>}/><Route path="/efficacy" element={<EfficacyPage/>}/><Route path="/health" element={<HealthPage/>}/><Route path="/tasks" element={<TasksPage/>}/><Route path="/tasks/:taskId" element={<TasksPage/>}/><Route path="*" element={<Navigate to="/" replace/>}/>
  </Routes></Suspense></Shell></DashboardProvider>
}
