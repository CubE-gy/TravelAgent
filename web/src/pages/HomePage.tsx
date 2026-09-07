import { ArrowRight, CalendarDays, LoaderCircle, MapPinned, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { getTrips } from "@/api/client";
import type { Trip } from "@/api/types";
import { Button } from "@/components/ui/button";

function dateRange(trip: Trip) {
  const format = (value: string) => value.replaceAll("-", ".");
  if (trip.start_date && trip.end_date) return `${format(trip.start_date)} — ${format(trip.end_date)}`;
  if (trip.start_date) return `出发 ${format(trip.start_date)}`;
  if (trip.end_date) return `返程 ${format(trip.end_date)}`;
  return "日期待补充";
}

function updatedLabel(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "最近更新";
  return `更新于 ${new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(date)}`;
}

export function HomePage() {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getTrips().then((data) => {
      if (!cancelled) setTrips(data);
    }).catch((reason: unknown) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : "旅行列表加载失败。");
    }).finally(() => {
      if (!cancelled) setIsLoading(false);
    });
    return () => { cancelled = true; };
  }, [reloadCount]);

  return <main className="min-h-svh bg-slate-50 text-slate-950">
    <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
      <div className="flex items-center gap-3"><span className="rounded-xl bg-sky-700 p-2 text-white"><MapPinned className="size-5" /></span>
        <h1 className="text-base font-semibold tracking-tight">TravelAgent</h1>
      </div>
      <Button asChild className="rounded-xl bg-sky-700 text-white hover:bg-sky-800"><Link to="/new"><Plus className="size-4" />新旅行</Link></Button>
    </header>
    <section className="mx-auto max-w-4xl px-5 py-12 sm:px-8">
      <p className="text-sm font-medium text-sky-700">旅行地图工作台</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4"><div>
        <h2 className="text-3xl font-semibold tracking-tight">已保存的旅行</h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">从这里继续对话，并在地图上查看已经确认的地点。</p>
      </div>
      <Button asChild variant="outline"><Link to="/new"><Plus className="size-4" />开始一趟新旅行</Link></Button></div>

      {isLoading ? <div className="flex min-h-52 items-center gap-2 text-sm text-slate-500" role="status"><LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />正在读取已保存的旅行…</div> : null}
      {error ? <div className="mt-8 rounded-2xl border border-red-100 bg-red-50 p-5 text-sm text-red-700" role="alert"><p>无法加载已保存的旅行：{error}</p><Button className="mt-4" onClick={() => setReloadCount((value) => value + 1)}><RefreshCw className="size-4" />重新加载</Button></div> : null}
      {!isLoading && !error && trips.length === 0 ? <div className="mt-8 rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center"><span className="inline-flex rounded-2xl bg-sky-50 p-3 text-sky-700"><MapPinned className="size-7" /></span><h3 className="mt-5 text-lg font-semibold">还没有保存的旅行</h3><p className="mt-2 text-sm text-slate-500">告诉 Agent 想去哪里，地点会随着对话保存到地图工作台。</p><Button asChild className="mt-6 bg-sky-700 text-white hover:bg-sky-800"><Link to="/new"><Plus className="size-4" />创建第一趟旅行</Link></Button></div> : null}
      {!isLoading && !error && trips.length > 0 ? <ul className="mt-8 grid gap-3" aria-label="已保存的旅行列表">{trips.map((trip) => <li key={trip.id}><Link className="group flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-sky-300 hover:shadow" to={`/trips/${trip.id}`}><span className="rounded-xl bg-sky-50 p-3 text-sky-700"><MapPinned className="size-5" /></span><span className="min-w-0 flex-1"><span className="block truncate text-base font-semibold">{trip.name ?? "未命名旅行"}</span><span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500"><span className="inline-flex items-center gap-1"><CalendarDays className="size-3.5" />{dateRange(trip)}</span><span>{updatedLabel(trip.updated_at)}</span></span></span><ArrowRight className="size-5 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-sky-700" /></Link></li>)}</ul> : null}
    </section>
  </main>;
}
