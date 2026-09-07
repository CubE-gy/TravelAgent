import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppRoutes } from "@/App";
import * as api from "@/api/client";
import type { ResolvedCity, Trip, TripConversationRead, TripState, TripWorkspace } from "@/api/types";
import type { MapLocation } from "@/map/locations";

vi.mock("@/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/api/client")>()),
  createTripFromFirstMessage: vi.fn(), getTrips: vi.fn(), getTripWorkspace: vi.fn(), sendTripMessage: vi.fn(), selectTripRecommendation: vi.fn(),
}));
vi.mock("@/map/AmapMap", () => ({
  AmapMap: ({ selectedLocationId, locations, city, onSelectLocation }: {
    selectedLocationId: string | null; locations: MapLocation[];
    city: ResolvedCity | null; onSelectLocation: (id: string) => void;
  }) => <div data-testid="map">
    <span data-testid="selection">{selectedLocationId ?? "none"}</span>
    <span>{city?.name}</span>
    {locations.map((item) => <button key={item.id} onClick={() => onSelectLocation(item.id)}>{`地图：${item.location.name}`}</button>)}
  </div>,
}));

function LocationProbe() { return <p data-testid="location">{useLocation().pathname}</p>; }
function renderRoutes(path = "/trips/trip-1") {
  return render(<MemoryRouter initialEntries={[path]}><AppRoutes /><LocationProbe /></MemoryRouter>);
}
const city: ResolvedCity = { name: "南京市", adcode: "320100", city_code: "025", center: { latitude: 32.06, longitude: 118.8 } };
const state: TripState = { trip_id: "trip-1", revision: 3, origin: null,
  destination: { query: "南京", resolution_status: "resolved", resolved_location: null, resolved_city: city, candidates: [] },
  return_destination: null, outbound_departure_station: null, outbound_arrival_station: null, accommodation: null, places: [] };
const workspace: TripWorkspace = {
  trip: { id: "trip-1", name: null, start_date: null, end_date: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  state, public_transport_plan: null,
};
const savedTrip: Trip = { id: "saved-trip", name: "南京周末", start_date: "2026-10-01", end_date: "2026-10-03", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-06T00:00:00Z" };
function place(poiId: string, name: string) {
  return { query: name, resolution_status: "resolved" as const, candidates: [],
    resolved_location: { poi_id: poiId, name, address: "南京市玄武区", coordinate: { latitude: 32.06, longitude: 118.85 } } };
}
function reply(nextState: TripState): TripConversationRead {
  return { state: nextState, revision: nextState.revision, location_failures: [], clarification: { questions: [] }, assistant_message: "后端 Agent 已处理旅行信息。" };
}
async function send(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("旅行消息"), text);
  await user.click(screen.getByRole("button", { name: "发送消息" }));
}

describe("conversation map workspace", () => {
  beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear(); });

  it("starts with chat and map on the new-trip page, then retains both first messages after creation", async () => {
    vi.mocked(api.createTripFromFirstMessage).mockResolvedValue({ ...reply(state), trip: workspace.trip });
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    renderRoutes("/new");
    expect(screen.getByRole("region", { name: "与旅行 Agent 对话" })).toBeInTheDocument();
    expect(screen.getByTestId("map")).toBeInTheDocument();
    await send("我想去南京");
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/trips/trip-1"));
    expect(screen.getByRole("log")).toHaveTextContent("我想去南京");
    expect(screen.getByRole("log")).toHaveTextContent("后端 Agent 已处理旅行信息");
    expect(screen.getByTestId("map")).toHaveTextContent("南京市");
  });

  it("shows the Agent response and adds a marker using the committed state", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    const next = { ...state, revision: 4, places: [place("sun", "中山陵")] };
    vi.mocked(api.sendTripMessage).mockResolvedValue(reply(next));
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("我还想去中山陵");
    expect(api.sendTripMessage).toHaveBeenCalledWith("trip-1", "我还想去中山陵", 3, []);
    expect(await screen.findByRole("button", { name: "地图：中山陵" })).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent("后端 Agent 已处理旅行信息");
    expect(api.getTripWorkspace).toHaveBeenCalledTimes(1);
  });

  it("keeps conversation history and uses the new revision on the next message", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    vi.mocked(api.sendTripMessage).mockResolvedValueOnce(reply({ ...state, revision: 4, places: [place("sun", "中山陵")] }))
      .mockResolvedValueOnce(reply({ ...state, revision: 5, places: [place("sun", "中山陵"), place("lake", "玄武湖")] }));
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("我还想去中山陵");
    await screen.findByRole("button", { name: "地图：中山陵" });
    await send("再加上玄武湖");
    expect(api.sendTripMessage).toHaveBeenLastCalledWith("trip-1", "再加上玄武湖", 4, [
      { role: "user", content: "我还想去中山陵" },
      { role: "assistant", content: "后端 Agent 已处理旅行信息。" },
    ]);
    expect(await screen.findByRole("button", { name: "地图：玄武湖" })).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveTextContent("我还想去中山陵");
    expect(screen.getByRole("log")).toHaveTextContent("再加上玄武湖");
  });

  it("removes a selected marker and its list entry after deletion", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace, state: { ...state, places: [place("sun", "中山陵")] } });
    vi.mocked(api.sendTripMessage).mockResolvedValue(reply({ ...state, revision: 4 }));
    const user = userEvent.setup();
    renderRoutes();
    await user.click(await screen.findByRole("button", { name: "地图：中山陵" }));
    expect(screen.getByTestId("selection")).toHaveTextContent("place-sun");
    await user.click(screen.getByText("地点清单", { exact: false }));
    expect(within(screen.getByRole("list", { name: "地点列表" })).getByRole("button", { name: "中山陵" })).toBeInTheDocument();
    await send("删除中山陵");
    await waitFor(() => expect(screen.queryByRole("button", { name: "地图：中山陵" })).not.toBeInTheDocument());
    expect(screen.getByTestId("selection")).toHaveTextContent("none");
    expect(screen.getByRole("log")).toHaveTextContent("后端 Agent 已处理旅行信息");
    expect(screen.queryByRole("button", { name: "中山陵" })).not.toBeInTheDocument();
  });

  it("replaces a corrected location and marks old transport data stale", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace,
      state: { ...state, accommodation: place("hotel-old", "原酒店") },
      public_transport_plan: { trip_id: "trip-1", source_state_revision: 3, stale: false, nodes: [] } });
    vi.mocked(api.sendTripMessage).mockResolvedValue(reply({ ...state, revision: 4, accommodation: place("hotel-new", "金陵饭店") }));
    renderRoutes();
    await screen.findByRole("button", { name: "地图：原酒店" });
    await send("酒店改成金陵饭店");
    expect(await screen.findByRole("button", { name: "地图：金陵饭店" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "地图：原酒店" })).not.toBeInTheDocument();
  });

  it("displays clarification in chat without a compulsory candidate picker", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    vi.mocked(api.sendTripMessage).mockResolvedValue({
      ...reply({ ...state, revision: 4, accommodation: { query: "如家", resolution_status: "ambiguous",
        candidates: [place("a", "如家甲店").resolved_location, place("b", "如家乙店").resolved_location], resolved_location: null } }),
      clarification: { questions: [{ topic_id: "confirm:accommodation", question: "你订的酒店有完整名称或地址吗？" }] },
      assistant_message: "你订的酒店有完整名称或地址吗？",
    });
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("住如家");
    expect(await screen.findByText(/你订的酒店有完整名称或地址吗/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /如家甲店/ })).not.toBeInTheDocument();
  });

  it("shows temporary map recommendations and clears them after the user clicks one", async () => {
    const hotel = place("hotel", "金陵饭店").resolved_location;
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    vi.mocked(api.sendTripMessage).mockResolvedValue({ ...reply(state),
      assistant_message: "我找到了 1 个附近酒店，你可以点击选择。",
      recommendations: [{ kind: "accommodation", location: hotel }],
      recommendation_session_id: "session-1",
    });
    vi.mocked(api.selectTripRecommendation).mockResolvedValue(reply({ ...state, revision: 4, accommodation: place("hotel", "金陵饭店") }));
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("推荐附近酒店");
    const recommendationPanel = await screen.findByRole("region", { name: "地图推荐" });
    const card = within(recommendationPanel).getByRole("button", { name: /金陵饭店/ });
    expect(screen.getByTestId("map")).toHaveTextContent("地图：金陵饭店");
    await userEvent.setup().click(card);
    expect(api.selectTripRecommendation).toHaveBeenCalledWith("trip-1", { kind: "accommodation", location: hotel }, 3, "session-1");
    await waitFor(() => expect(screen.queryByRole("region", { name: "地图推荐" })).not.toBeInTheDocument());
    expect(screen.getByRole("log")).toHaveTextContent("后端 Agent 已处理旅行信息");
  });

  it("keeps pending cards as reference context when the user refines a recommendation", async () => {
    const ordinary = place("hotel-1", "普通酒店").resolved_location;
    const premium = place("hotel-2", "高档酒店").resolved_location;
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    vi.mocked(api.sendTripMessage).mockResolvedValueOnce({ ...reply(state), recommendations: [{ kind: "accommodation", location: ordinary }], recommendation_session_id: "session-1" })
      .mockResolvedValueOnce({ ...reply(state), recommendations: [{ kind: "accommodation", location: premium }], recommendation_session_id: "session-2" });
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("推荐附近酒店");
    await within(await screen.findByRole("region", { name: "地图推荐" })).findByRole("button", { name: /普通酒店/ });
    await send("我想要档次高一些的");
    expect(api.sendTripMessage).toHaveBeenLastCalledWith("trip-1", "我想要档次高一些的", 3, [
      { role: "user", content: "推荐附近酒店" },
      { role: "assistant", content: "后端 Agent 已处理旅行信息。" },
    ], { recommendation_session_id: "session-1" });
    const refreshedPanel = await screen.findByRole("region", { name: "地图推荐" });
    expect(within(refreshedPanel).getByRole("button", { name: /高档酒店/ })).toBeInTheDocument();
    expect(within(refreshedPanel).queryByRole("button", { name: /普通酒店/ })).not.toBeInTheDocument();
  });

  it("keeps the input and old markers when sending fails", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace, state: { ...state, places: [place("sun", "中山陵")] } });
    vi.mocked(api.sendTripMessage).mockRejectedValue(new Error("服务暂时不可用"));
    renderRoutes();
    await screen.findByRole("button", { name: "地图：中山陵" });
    await send("删除中山陵");
    expect(await screen.findByRole("alert")).toHaveTextContent("服务暂时不可用");
    expect(screen.getByLabelText("旅行消息")).toHaveValue("删除中山陵");
    expect(screen.getByRole("button", { name: "地图：中山陵" })).toBeInTheDocument();
    expect(screen.getByRole("log")).not.toHaveTextContent("已移除");
  });

  it("reports a map lookup failure without pretending to have marked a place", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue(workspace);
    vi.mocked(api.sendTripMessage).mockResolvedValue({ ...reply({ ...state, revision: 4, places: [{ query: "中山陵", resolution_status: "unresolved", resolved_location: null, candidates: [] }] }),
      location_failures: [{ field: "places", place_index: 0, query: "中山陵", error_code: "map_timeout" }] });
    vi.mocked(api.sendTripMessage).mockResolvedValue({ ...reply({ ...state, revision: 4, places: [{ query: "中山陵", resolution_status: "unresolved", resolved_location: null, candidates: [] }] }),
      location_failures: [{ field: "places", place_index: 0, query: "中山陵", error_code: "map_timeout" }], assistant_message: "中山陵的地图查询暂时失败。" });
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("加上中山陵");
    expect(await screen.findByText(/地图查询暂时失败/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "地图：中山陵" })).not.toBeInTheDocument();
  });

  it("reloads after a revision conflict without automatically resending", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValueOnce(workspace).mockResolvedValueOnce({ ...workspace, state: { ...state, revision: 9 } });
    vi.mocked(api.sendTripMessage).mockRejectedValue(new api.ApiError("stale", 409));
    renderRoutes();
    await screen.findByText(/已载入这趟旅行/);
    await send("增加中山陵");
    expect(await screen.findByRole("alert")).toHaveTextContent("已载入最新地点");
    expect(api.getTripWorkspace).toHaveBeenCalledTimes(2);
    expect(api.sendTripMessage).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("旅行消息")).toHaveValue("增加中山陵");
  });

  it("allows an existing trip without state to start a conversation", async () => {
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace, state: null });
    vi.mocked(api.sendTripMessage).mockResolvedValue(reply(state));
    renderRoutes();
    await screen.findByText(/告诉我目的地/);
    await send("我想去南京");
    expect(api.sendTripMessage).toHaveBeenCalledWith("trip-1", "我想去南京", 0, []);
    expect(screen.getByTestId("map")).toHaveTextContent("南京市");
  });

  it("shows loading, an error and a working retry for workspace reads", async () => {
    vi.mocked(api.getTripWorkspace).mockRejectedValueOnce(new Error("Trip not found")).mockResolvedValueOnce(workspace);
    const user = userEvent.setup();
    renderRoutes();
    expect(screen.getByText("正在加载旅行工作台…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载旅行工作台：Trip not found");
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText(/已载入这趟旅行/)).toBeInTheDocument();
  });

  it("restores this tab's chat while fetching current persisted map state", async () => {
    sessionStorage.setItem("travel-chat:trip-1", JSON.stringify([{ id: "m", role: "user", content: "我想去南京" }]));
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace, state: { ...state, revision: 8, places: [place("lake", "玄武湖")] } });
    renderRoutes();
    expect(screen.getByRole("log")).toHaveTextContent("我想去南京");
    expect(await screen.findByRole("button", { name: "地图：玄武湖" })).toBeInTheDocument();
  });
});

describe("saved trip list", () => {
  beforeEach(() => { vi.resetAllMocks(); });

  it("shows saved trips and opens the selected workspace", async () => {
    vi.mocked(api.getTrips).mockResolvedValue([savedTrip]);
    vi.mocked(api.getTripWorkspace).mockResolvedValue({ ...workspace, trip: savedTrip });
    const user = userEvent.setup();
    renderRoutes("/");
    expect(screen.getByRole("status")).toHaveTextContent("正在读取已保存的旅行");
    const item = await screen.findByRole("link", { name: /南京周末/ });
    expect(item).toHaveTextContent("2026.10.01 — 2026.10.03");
    await user.click(item);
    expect(screen.getByTestId("location")).toHaveTextContent("/trips/saved-trip");
  });

  it("guides the user to create a trip when none have been saved", async () => {
    vi.mocked(api.getTrips).mockResolvedValue([]);
    renderRoutes("/");
    expect(await screen.findByText("还没有保存的旅行")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "创建第一趟旅行" })).toHaveAttribute("href", "/new");
  });

  it("shows a failed list load and retries it", async () => {
    vi.mocked(api.getTrips).mockRejectedValueOnce(new Error("服务暂不可用")).mockResolvedValueOnce([savedTrip]);
    const user = userEvent.setup();
    renderRoutes("/");
    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载已保存的旅行：服务暂不可用");
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("link", { name: /南京周末/ })).toBeInTheDocument();
  });
});
