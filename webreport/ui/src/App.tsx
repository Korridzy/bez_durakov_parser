import {
  BrowserRouter,
  NavLink,
  Navigate,
  Route,
  Routes,
  useParams,
} from "react-router-dom";

function ChatsPage() {
  const { chatId } = useParams();
  return (
    <section className="page" aria-labelledby="chats-heading">
      <h1 id="chats-heading">Чаты</h1>
      <p className="page-lead">
        {chatId === undefined
          ? "Выберите чат или начните новый."
          : `Чат ${chatId}`}
      </p>
    </section>
  );
}

function SavedReportsPage() {
  const { reportId } = useParams();
  return (
    <section className="page" aria-labelledby="saved-heading">
      <h1 id="saved-heading">Сохранённые отчёты</h1>
      <p className="page-lead">
        {reportId === undefined
          ? "Здесь появятся сохранённые отчёты."
          : `Отчёт ${reportId}`}
      </p>
    </section>
  );
}

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="app-brand">Отчёты по данным</p>
        <nav className="app-tabs" aria-label="Разделы">
          <NavLink className="app-tab" to="/chats">
            Чаты
          </NavLink>
          <NavLink className="app-tab" to="/saved">
            Сохранённые отчёты
          </NavLink>
        </nav>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<Navigate to="/chats" replace />} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/chats/:chatId" element={<ChatsPage />} />
          <Route path="/saved" element={<SavedReportsPage />} />
          <Route path="/saved/:reportId" element={<SavedReportsPage />} />
          <Route path="*" element={<Navigate to="/chats" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  );
}
