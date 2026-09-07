import { ArrowUp, List, LoaderCircle, MapPinned, MessageCircleMore, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { ApiError, createTripFromFirstMessage, getTripWorkspace, selectTripRecommendation, sendTripMessage } from "@/api/client";
import type { TripRecommendation, TripRecommendationContext, TripWorkspace } from "@/api/types";
import { LocationList } from "@/components/LocationList";
import { Button } from "@/components/ui/button";
import { agentReply, chatMessage, readChat, recentConversationContext, saveChat, type ChatMessage } from "@/lib/conversation";
import { AmapMap } from "@/map/AmapMap";
import { mapLocationsWithRecommendations, reconcileSelectedLocationId } from "@/map/locations";

export function WorkspacePage() {
  const { tripId } = useParams();
  const navigate = useNavigate();
  const route = useLocation();
  const seed = (route.state as { workspace?: TripWorkspace } | null)?.workspace;
  const [workspace, setWorkspace] = useState<TripWorkspace | null>(seed && seed.trip.id === tripId ? seed : null);
  const [isLoading, setIsLoading] = useState(Boolean(tripId && !seed));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>(() => tripId ? readChat(tripId) : []);
  const [actionError, setActionError] = useState<string | null>(null);
  const [recommendations, setRecommendations] = useState<TripRecommendation[]>([]);
  const [recommendationSessionId, setRecommendationSessionId] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const sendingRef = useRef(false);
  const activeRef = useRef(true);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const mapLocations = useMemo(() => workspace
    ? mapLocationsWithRecommendations(workspace.state, workspace.public_transport_plan, recommendations) : [], [workspace, recommendations]);
  const city = workspace?.state?.destination?.resolved_city ?? null;

  useEffect(() => {
    activeRef.current = true;
    return () => { activeRef.current = false; };
  }, []);

  useEffect(() => {
    if (!tripId) return;
    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    getTripWorkspace(tripId).then((data) => {
      if (!cancelled) setWorkspace(data);
    }).catch((error: unknown) => {
      if (!cancelled) setLoadError(error instanceof Error ? error.message : "加载旅行失败。");
    }).finally(() => { if (!cancelled) setIsLoading(false); });
    return () => { cancelled = true; };
  }, [tripId, seed, reloadCount]);

  useEffect(() => {
    setSelectedLocationId((current) => reconcileSelectedLocationId(current, mapLocations));
  }, [mapLocations]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, isSending]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();
    if (!trimmedMessage || sendingRef.current || isLoading || loadError) return;
    sendingRef.current = true;
    setIsSending(true);
    setActionError(null);
    const userMessage = chatMessage("user", trimmedMessage);
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setMessage("");
    try {
      if (!tripId) {
        const result = await createTripFromFirstMessage(trimmedMessage, recentConversationContext(messages));
        const history = [...nextMessages, chatMessage("assistant", agentReply(result))];
        saveChat(result.trip.id, history);
        if (!activeRef.current) return;
        navigate(`/trips/${result.trip.id}`, { state: { workspace: {
          trip: result.trip, state: result.state, public_transport_plan: null,
        } } });
      } else {
        const recommendationContext: TripRecommendationContext | undefined = recommendationSessionId
          ? { recommendation_session_id: recommendationSessionId } : undefined;
        const result = recommendationContext
          ? await sendTripMessage(tripId, trimmedMessage, workspace?.state?.revision ?? 0,
            recentConversationContext(messages), recommendationContext)
          : await sendTripMessage(tripId, trimmedMessage, workspace?.state?.revision ?? 0,
            recentConversationContext(messages));
        if (!activeRef.current) return;
        // Use the committed response so a second fetch cannot revive stale markers.
        setWorkspace((current) => current ? {
          ...current, state: result.state,
          public_transport_plan: current.public_transport_plan ? {
            ...current.public_transport_plan,
            stale: current.public_transport_plan.source_state_revision !== result.revision,
          } : null,
        } : current);
        setRecommendations(result.recommendations ?? []);
        setRecommendationSessionId(result.recommendation_session_id ?? null);
        const history = [...nextMessages, chatMessage("assistant", agentReply(result))];
        setMessages(history);
        saveChat(tripId, history);
      }
    } catch (error) {
      if (!activeRef.current) return;
      const history = nextMessages.map((item) => item.id === userMessage.id ? { ...item, failed: true } : item);
      setMessages(history);
      if (tripId) saveChat(tripId, history);
      setMessage(trimmedMessage);
      if (error instanceof ApiError && error.status === 409 && tripId) {
        try {
          const latest = await getTripWorkspace(tripId);
          if (!activeRef.current) return;
          setWorkspace(latest);
          setActionError("旅行已在其他页面更新，已载入最新地点。请检查后重新发送这条消息。");
        } catch {
          if (activeRef.current) setActionError("旅行已在其他页面更新，最新地点加载失败。请刷新页面后重试。");
        }
      } else {
        setActionError(error instanceof Error ? error.message : "发送失败，请稍后重试。");
      }
    } finally {
      sendingRef.current = false;
      if (activeRef.current) {
        setIsSending(false);
        inputRef.current?.focus();
      }
    }
  }

  async function handleRecommendationSelection(recommendation: TripRecommendation) {
    if (!tripId || !workspace || isSending) return;
    setIsSending(true);
    setActionError(null);
    try {
      const result = recommendationSessionId
        ? await selectTripRecommendation(tripId, recommendation, workspace.state?.revision ?? 0, recommendationSessionId)
        : await selectTripRecommendation(tripId, recommendation, workspace.state?.revision ?? 0);
      setWorkspace((current) => current ? { ...current, state: result.state,
        public_transport_plan: current.public_transport_plan ? { ...current.public_transport_plan, stale: current.public_transport_plan.source_state_revision !== result.revision } : null } : current);
      setRecommendations([]);
      setRecommendationSessionId(null);
      const history = [...messages, chatMessage("assistant", agentReply(result))];
      setMessages(history);
      saveChat(tripId, history);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "地点确认失败，请稍后重试。");
    } finally { if (activeRef.current) setIsSending(false); }
  }

  const busy = isSending || isLoading || Boolean(loadError);
  return (
    <main className="flex min-h-svh flex-col bg-slate-50 text-slate-950 lg:h-svh lg:overflow-hidden">
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-7">
        <div className="flex min-w-0 items-center gap-3">
          <span className="rounded-xl bg-sky-700 p-2 text-white"><MapPinned className="size-5" /></span>
          <div className="min-w-0"><h1 className="text-base font-semibold tracking-tight">TravelAgent</h1>
            <p className="truncate text-xs text-slate-500">{city ? `${city.name} · 旅行地图` : workspace?.trip.name ?? "和我聊聊你的下一趟旅行"}</p>
          </div>
        </div>
        <Link className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100" to="/new"><Plus className="size-4" />新旅行</Link>
      </header>

      <div className="grid flex-1 min-h-0 lg:grid-cols-2">
        <section aria-label="与旅行 Agent 对话" className="flex min-h-[32rem] flex-col border-b border-slate-200 bg-white lg:min-h-0 lg:border-b-0 lg:border-r">
          <div className="flex shrink-0 items-center gap-2 border-b border-slate-100 px-6 py-4 text-sm font-medium">
            <MessageCircleMore className="size-4 text-sky-700" />旅行对话
            <span className="ml-auto text-xs font-normal text-slate-400">边聊边看地图</span>
          </div>
          <div className="flex-1 overflow-y-auto px-5 py-6 sm:px-8" role="log" aria-label="对话记录" aria-live="polite">
            {isLoading ? <p role="status" className="text-sm text-slate-500">正在加载旅行工作台…</p> : null}
            {loadError ? <div role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">
              <p>无法加载旅行工作台：{loadError}</p>
              <Button className="mt-3" onClick={() => setReloadCount((value) => value + 1)}>重新加载</Button>
            </div> : null}
            {!messages.length && !isLoading && !loadError ? <div className="mx-auto max-w-lg py-8">
              <span className="mb-5 inline-flex rounded-2xl bg-sky-50 p-3 text-sky-700"><MapPinned className="size-7" /></span>
              <h2 className="text-2xl font-semibold leading-relaxed">想去哪里？<br />我们一起把地点放上地图。</h2>
              <p className="mt-4 text-sm leading-7 text-slate-500">{workspace?.state
                ? "已载入这趟旅行的地点。你可以继续补充景点、酒店和车站，也可以直接告诉我想修改什么。"
                : "告诉我目的地，再慢慢补充景点、酒店和车站。我会结合城市自动匹配地点，帮你看清它们的位置。"}</p>
              {!tripId ? <button className="mt-6 rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700 hover:border-sky-300 hover:bg-sky-50" type="button" onClick={() => { setMessage("我想去南京"); inputRef.current?.focus(); }}>试试：我想去南京</button> : null}
            </div> : null}
            <div className="mx-auto max-w-2xl space-y-6">
              {messages.map((item) => <article className={`flex ${item.role === "user" ? "justify-end" : "justify-start"}`} key={item.id}>
                <div className={`max-w-[92%] ${item.role === "user" ? "rounded-2xl rounded-tr-sm bg-sky-700 px-4 py-3 text-white" : "py-1 text-slate-700"}`}>
                  <p className={`mb-1.5 text-xs font-medium ${item.role === "user" ? "text-sky-100" : "text-sky-700"}`}>{item.role === "user" ? "你" : "TravelAgent"}</p>
                  <p className="whitespace-pre-wrap break-words text-sm leading-7">{item.content}</p>
                  {item.failed ? <p className="mt-2 text-xs text-sky-100">未发送成功，请查看下方提示。</p> : null}
                </div>
              </article>)}
              {recommendations.length ? <section aria-label="地图推荐" className="rounded-2xl border border-violet-200 bg-violet-50 p-4">
                <p className="text-sm font-semibold text-violet-900">地图推荐</p><p className="mt-1 text-xs text-violet-700">点击后确认并仅保留该推荐地点。</p>
                <div className="mt-3 grid gap-2">{recommendations.map((recommendation) => <button className="rounded-xl border border-violet-200 bg-white p-3 text-left hover:border-violet-400 hover:bg-violet-50" key={recommendation.location.poi_id} onClick={() => handleRecommendationSelection(recommendation)} type="button">
                  <span className="block text-sm font-semibold text-slate-800">{recommendation.location.name}</span><span className="mt-1 block text-xs text-slate-500">{recommendation.location.address ?? "高德已确认地点"}</span>
                </button>)}</div>
              </section> : null}
              {isSending ? <p className="flex items-center gap-2 text-sm text-slate-500" role="status"><LoaderCircle className="size-4 animate-spin motion-reduce:animate-none" />正在理解需求并查找地图地点…</p> : null}
              <div ref={chatEndRef} />
            </div>
          </div>
          <form className="shrink-0 border-t border-slate-100 bg-white px-5 pb-5 pt-4 sm:px-8" onSubmit={handleSubmit}>
            {actionError ? <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{actionError}</p> : null}
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3 focus-within:border-sky-400 focus-within:ring-2 focus-within:ring-sky-50">
              <textarea aria-label="旅行消息" ref={inputRef} className="min-h-20 max-h-40 w-full resize-y bg-transparent px-1 text-sm leading-6 outline-none placeholder:text-slate-400" disabled={busy} maxLength={5000} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault(); event.currentTarget.form?.requestSubmit();
                }
              }} placeholder={tripId ? "例如：我还想去中山陵，酒店是南京金陵饭店" : "例如：我想去南京"} value={message} />
              <div className="flex items-center justify-between gap-3"><p className="text-[11px] text-slate-400">Enter 发送 · Shift + Enter 换行</p>
                <Button aria-label="发送消息" className="rounded-xl bg-sky-700 text-white hover:bg-sky-800" disabled={busy || !message.trim()} type="submit"><ArrowUp className="size-4" /><span>发送</span></Button>
              </div>
            </div>
          </form>
        </section>

        <section aria-label="地点与地图" className="flex min-h-[32rem] min-w-0 flex-col gap-3 p-3 lg:min-h-0 lg:p-4">
          <div className="min-h-[28rem] flex-1 lg:min-h-0"><AmapMap city={city} locations={mapLocations} onSelectLocation={setSelectedLocationId} selectedLocationId={selectedLocationId} transportPlanStale={workspace?.public_transport_plan?.stale === true} /></div>
          <details className="shrink-0 overflow-hidden rounded-xl border border-slate-200 bg-white">
            <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-slate-700"><List className="mr-2 inline size-4" />地点清单 <span className="ml-2 text-xs font-normal text-slate-400">{mapLocations.length} 个已定位地点 · 展开查看</span></summary>
            <div className="max-h-64 overflow-y-auto border-t border-slate-100 p-3">
              <LocationList locations={mapLocations} onSelect={setSelectedLocationId} selectedLocationId={selectedLocationId} state={workspace?.state ?? null} transportPlanStale={workspace?.public_transport_plan?.stale === true} />
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}
