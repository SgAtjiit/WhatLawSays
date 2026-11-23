import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";

import { AuthProvider } from "@/auth/AuthProvider";
import { DEMO_ENABLED } from "@/auth/demo";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppShell } from "@/components/AppShell";
import { Splash } from "@/components/Splash";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Home } from "@/routes/Home";
import { NotFound } from "@/routes/NotFound";
import { ResetPassword, SignIn, SignUp, VerifyEmail } from "@/routes/auth";
import { DemoSignIn } from "@/routes/DemoSignIn";

// The tools load on demand, so the landing and sign-in screens stay light.
const Scenario = lazy(() => import("@/routes/Scenario"));
const ContractUpload = lazy(() => import("@/routes/ContractUpload"));
const ContractReview = lazy(() => import("@/routes/ContractReview"));
const MyReviews = lazy(() => import("@/routes/MyReviews"));
const Companion = lazy(() => import("@/routes/Companion"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => count < 1 && ["offline", "server", "timeout"].includes(error?.kind),
    },
  },
});

const page = (element) => <Suspense fallback={<Splash />}>{element}</Suspense>;

const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Home /> },
      { path: "sign-in", element: <SignIn /> },
      { path: "sign-up", element: <SignUp /> },
      { path: "reset-password", element: <ResetPassword /> },
      { path: "verify-email", element: <VerifyEmail /> },
      ...(DEMO_ENABLED ? [{ path: "demo/:id", element: <DemoSignIn /> }] : []),
      {
        element: <RequireAuth />,
        children: [
          { path: "scenario", element: page(<Scenario />) },
          { path: "contracts", element: page(<ContractUpload />) },
          { path: "contracts/:contractId", element: page(<ContractReview />) },
          { path: "reviews", element: page(<MyReviews />) },
          { path: "talk/:conversationId?", element: page(<Companion />) },
        ],
      },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider delayDuration={300}>
          <RouterProvider router={router} />
          <Toaster position="bottom-center" />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
