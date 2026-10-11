import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { MarketingLayout } from './layouts/MarketingLayout';
import { AppLayout } from './layouts/AppLayout';
import { DraftProvider } from './lib/draft';
import { AuthProvider } from './lib/auth';

const Landing = lazy(() => import('./pages/Landing'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const NewReel = lazy(() => import('./pages/NewReel'));
const ReelPage = lazy(() => import('./pages/ReelPage'));
const History = lazy(() => import('./pages/History'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const Pricing = lazy(() => import('./pages/Pricing'));
const Login = lazy(() => import('./pages/Login'));
const NotFound = lazy(() => import('./pages/NotFound'));

const Fallback = () => (
  <div className="grid min-h-[40vh] place-items-center" role="status" aria-label="Loading">
    <div className="h-6 w-6 animate-spin rounded-full border-2 border-line border-t-violet" />
  </div>
);

export default function App() {
  return (
    <AuthProvider>
    <DraftProvider>
      <Suspense fallback={<Fallback />}>
        <Routes>
          <Route element={<MarketingLayout />}>
            <Route index element={<Landing />} />
          </Route>
          <Route path="login" element={<Login mode="login" />} />
          <Route path="register" element={<Login mode="register" />} />
          <Route path="app" element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="new" element={<NewReel />} />
            <Route path="history" element={<History />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="pricing" element={<Pricing />} />
          </Route>
          <Route path="reels/:jobId" element={<AppLayout />}>
            <Route index element={<ReelPage />} />
          </Route>
          <Route path="*" element={<MarketingLayout />}>
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </DraftProvider>
    </AuthProvider>
  );
}
