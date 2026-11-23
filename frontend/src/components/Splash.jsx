export function Splash() {
  return (
    <div role="status" aria-label="Loading" className="grid min-h-[60vh] place-items-center">
      <div className="h-0.5 w-24 overflow-hidden rounded-full bg-rule">
        <div className="h-full w-1/3 animate-[working_1.6s_var(--ease-out)_infinite] rounded-full bg-seal" />
      </div>
    </div>
  );
}
