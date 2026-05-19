import React, { Suspense, lazy, useEffect, useState, useCallback } from "react";
import { BrowserRouter as Router, Routes, Route, Navigate, Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ThemeProvider } from "@/context/ThemeContext";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { Toaster } from "@/components/ui/sonner";
import { DashboardLayout } from "@/components/layout/DashboardLayout";
import { CandidateLayout } from "@/components/layout/CandidateLayout";
import {
  AlertDialog, AlertDialogContent, AlertDialogHeader,
  AlertDialogTitle, AlertDialogDescription, AlertDialogFooter,
  AlertDialogAction,
} from "@/components/ui/alert-dialog";
import { LogIn, ShieldAlert } from "lucide-react";
import { clearSessionExpiredMark, isSessionExpiredMarked, setQuizToken } from "@/services/tokenStore";

const LandingPage = lazy(() => import("@/pages/Landing"));
const Login = lazy(() => import("@/pages/Login"));
const Signup = lazy(() => import("@/pages/Signup"));
const ForgotPassword = lazy(() => import("@/pages/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/ResetPassword"));
const QuizMagicEntry = lazy(() => import("@/pages/QuizMagicEntry"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Jobs = lazy(() => import("@/pages/Jobs"));
const JobDetails = lazy(() => import("@/pages/JobDetails"));
const Candidates = lazy(() => import("@/pages/Candidates"));
const CandidateDetails = lazy(() => import("@/pages/CandidateDetails"));
const Analytics = lazy(() => import("@/pages/Analytics"));
const Inspector = lazy(() => import("@/pages/Inspector"));
const Settings = lazy(() => import("@/pages/Settings"));
const CandidateDashboard = lazy(() => import("@/pages/CandidateDashboard"));
const CandidateProgress = lazy(() => import("@/pages/CandidateProgress"));
const CandidateJobBoard = lazy(() => import("@/pages/CandidateJobBoard"));
const CandidateJobDetail = lazy(() => import("@/pages/CandidateJobDetail"));
const CandidateCompanyPanel = lazy(() => import("@/pages/CandidateCompanyPanel"));
const CandidateApply = lazy(() => import("@/pages/CandidateApply"));
const CandidateFeedback = lazy(() => import("@/pages/CandidateFeedback"));
const CandidateMockTest = lazy(() => import("@/pages/CandidateMockTest"));
const CandidateSettings = lazy(() => import("@/pages/CandidateSettings"));
const CandidateCareerTools = lazy(() => import("@/pages/CandidateCareerTools"));

// Slim top progress bar shown while a lazy chunk loads.
// Keeps the layout stable and gives instant visual feedback.
function TopProgressBar() {
  const [width, setWidth] = useState(10);
  useEffect(() => {
    const t1 = setTimeout(() => setWidth(50), 100);
    const t2 = setTimeout(() => setWidth(75), 300);
    const t3 = setTimeout(() => setWidth(90), 1000);
    const t4 = setTimeout(() => setWidth(95), 3000);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); };
  }, []);
  
  return (
    <div
      className="fixed top-0 left-0 z-[9999] h-[2px] bg-primary transition-[width] duration-500 ease-out pointer-events-none"
      style={{ width: `${width}%` }}
    />
  );
}

function NotFoundPage() {
  const { isAuthenticated, user } = useAuth();
  const dashboardPath = isAuthenticated && user?.role === 'candidate' ? '/candidate/dashboard' : '/dashboard';
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 text-center px-4">
      <p className="text-7xl font-bold text-muted-foreground/30">404</p>
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground max-w-xs">
        The URL you requested doesn't exist. It may have been moved or deleted.
      </p>
      {/* FIX F-15: Use React Router <Link> instead of <a href> to avoid full SPA reloads */}
      {isAuthenticated ? (
        <Link to={dashboardPath} className="mt-2 inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          Go to dashboard
        </Link>
      ) : (
        <Link to="/login" className="mt-2 inline-flex items-center gap-2 rounded-full bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
          Go to login
        </Link>
      )}
    </div>
  );
}

function AuthLoader() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="h-6 w-6 rounded-full border-2 border-primary border-t-transparent animate-spin" />
    </div>
  );
}

function ProtectedRoute({ children, allowedRoles }: { children: React.ReactNode; allowedRoles?: string[] }) {
  const { user, loading, isAuthenticated } = useAuth();
  if (loading) return <AuthLoader />;
  if (!isAuthenticated) return <Navigate to="/login" />;
  if (allowedRoles && user && !allowedRoles.includes(user.role)) {
    if (user.role === "candidate") return <Navigate to="/candidate/dashboard" />;
    if (user.role === "hr" || user.role === "admin") return <Navigate to="/dashboard" />;
    // Unsupported role — log a warning so developers notice, and show a
    // user-facing message instead of silently redirecting to "/".
    console.warn(`[ProtectedRoute] Unrecognized user role: "${user.role}". Redirecting to root.`);
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 text-center px-4">
        <p className="text-lg font-semibold">Access not available</p>
        <p className="text-muted-foreground text-sm max-w-xs">
          Your account role (<code>{user.role}</code>) does not have access to this page.
          Please contact your administrator.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  if (isAuthenticated && user) {
    if (user.role === "candidate") return <Navigate to="/candidate/dashboard" />;
    return <Navigate to="/dashboard" />;
  }
  return <>{children}</>;
}

function LegacyQuizPathRedirect() {
  const { token } = useParams<{ token: string }>();
  const next = token ? `/take-quiz?token=${encodeURIComponent(token)}` : "/take-quiz";
  return <Navigate to={next} replace />;
}

function TakeQuizRoute() {
  const location = useLocation();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // SECURITY: token is stripped from URL immediately after read so it does not
    // appear in browser history or referrer headers on subsequent navigation.
    // Residual exposure: token appears in email body/mail provider logs (acceptable
    // given HTTPS delivery). Token TTL is 7 days; rotation on resend is enforced
    // server-side (quiz.py send_quiz_links).
    const token = new URLSearchParams(location.search).get('token');
    if (token) {
      setQuizToken(token);
      window.history.replaceState({}, '', location.pathname);
    }
    setReady(true);
  }, [location.pathname, location.search]);

  if (!ready) return <AuthLoader />;
  return <QuizMagicEntry />;
}
type RouteErrorBoundaryProps = { children: React.ReactNode };
type RouteErrorBoundaryState = { hasError: boolean; message: string };

class RouteErrorBoundary extends React.Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  declare props: RouteErrorBoundaryProps;
  state: RouteErrorBoundaryState = { hasError: false, message: "" };

  static getDerivedStateFromError(error: unknown) {
    const message = error instanceof Error ? error.message : "Unexpected route error";
    return { hasError: true, message };
  }

  componentDidCatch(error: unknown) {
    console.error("Route rendering failed:", error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen flex-col items-center justify-center gap-3 text-center px-4">
          <p className="text-lg font-semibold">Something went wrong while loading this page.</p>
          <p className="text-sm text-muted-foreground max-w-md">{this.state.message}</p>
          <button
            className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}


// ─── Session Expired Modal ──────────────────────────────────────────────────
// Listens for the `auth:session-expired` CustomEvent dispatched by api.ts
// whenever any API response returns 401. Clears auth state and forces the
// user back to /login so they re-authenticate with a fresh token.
function SessionExpiredModal() {
  const { logout, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  const handleExpiry = useCallback(() => {
    clearSessionExpiredMark();
    // Only open once — ignore duplicate events fired by concurrent requests.
    setOpen(prev => prev ? prev : true);
  }, []);

  useEffect(() => {
    window.addEventListener("auth:session-expired", handleExpiry);
    return () => window.removeEventListener("auth:session-expired", handleExpiry);
  }, [handleExpiry]);

  useEffect(() => {
    if (!isSessionExpiredMarked()) return;

    const path = location.pathname;
    const isQuizPath = path.startsWith('/take-quiz') || path.startsWith('/quiz/');
    if (isQuizPath) return;

    // Consume the flag once users leave quiz routes.
    clearSessionExpiredMark();
    if (!isAuthenticated) return;
    if (path.startsWith('/login')) return;
    setOpen(prev => prev ? prev : true);
  }, [location.pathname, isAuthenticated]);

  const handleConfirm = () => {
    setOpen(false);
    logout();
    // BUG-NEW-12 FIX: use React Router navigate instead of window.location.href.
    // The previous setTimeout(…, 50) was a race condition — if logout() took
    // longer than 50ms the navigation fired before auth state was cleared.
    navigate("/login");
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogContent className="max-w-sm rounded-2xl">
        <AlertDialogHeader>
          <div className="flex items-center gap-3 mb-1">
            <div className="p-2.5 rounded-xl bg-amber-100 dark:bg-amber-900/30">
              <ShieldAlert className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            </div>
            <AlertDialogTitle className="text-base">Session Expired</AlertDialogTitle>
          </div>
          <AlertDialogDescription className="text-sm leading-relaxed">
            Your session has timed out for security. Please sign in again to continue.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogAction
            className="rounded-full w-full flex items-center justify-center gap-2"
            onClick={handleConfirm}
          >
            <LogIn className="h-4 w-4" />
            Sign in again
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AppRoutes() {
  return (
    <RouteErrorBoundary>
      <Suspense fallback={<TopProgressBar />}>
        <Routes>
          {/* FIX F-14: Wrap / in PublicRoute so authenticated users redirect to their dashboard */}
          <Route path="/" element={<PublicRoute><LandingPage /></PublicRoute>} />
          <Route path="/login" element={<PublicRoute><Login /></PublicRoute>} />
          <Route path="/signup" element={<PublicRoute><Signup /></PublicRoute>} />
          <Route path="/forgot-password" element={<PublicRoute><ForgotPassword /></PublicRoute>} />
          <Route path="/reset-password/:token" element={<PublicRoute><ResetPassword /></PublicRoute>} />
          <Route path="/take-quiz" element={<TakeQuizRoute />} />
          <Route path="/quiz/:token" element={<LegacyQuizPathRedirect />} />

          <Route path="/dashboard" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><Dashboard /></DashboardLayout></ProtectedRoute>} />
          <Route path="/jobs" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><Jobs /></DashboardLayout></ProtectedRoute>} />
          <Route path="/jobs/:id" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><JobDetails /></DashboardLayout></ProtectedRoute>} />
          <Route path="/candidates" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><Candidates /></DashboardLayout></ProtectedRoute>} />
          <Route path="/candidates/:id" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><CandidateDetails /></DashboardLayout></ProtectedRoute>} />
          <Route path="/analytics" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><Analytics /></DashboardLayout></ProtectedRoute>} />
          <Route path="/inspector" element={<ProtectedRoute allowedRoles={["admin"]}><DashboardLayout><Inspector /></DashboardLayout></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute allowedRoles={["hr", "admin"]}><DashboardLayout><Settings /></DashboardLayout></ProtectedRoute>} />

          <Route path="/candidate/dashboard" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateDashboard /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/progress" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateProgress /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/jobs" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateJobBoard /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/company/:id" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateCompanyPanel /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/jobs/:id" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateJobDetail /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/apply/:id" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateApply /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/feedback/:id" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateFeedback /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/mock-test" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateMockTest /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/settings" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateSettings /></CandidateLayout></ProtectedRoute>} />
          <Route path="/candidate/career-tools" element={<ProtectedRoute allowedRoles={["candidate"]}><CandidateLayout><CandidateCareerTools /></CandidateLayout></ProtectedRoute>} />

          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </RouteErrorBoundary>
  );
}

export default function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="vite-ui-theme">
      <Router>
        <AuthProvider>
          <AppRoutes />
          <SessionExpiredModal />
          <Toaster />
        </AuthProvider>
      </Router>
    </ThemeProvider>
  );
}


