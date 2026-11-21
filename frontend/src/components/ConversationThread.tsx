import {
  BranchesOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  StopOutlined,
  ToolOutlined,
} from "@ant-design/icons";
import { Button, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";
import { getDownloadUrl } from "../lib/api";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { MonitorMessage, OutputFile } from "../types";

export interface ChatTurn {
  id: string;
  content: string;
  events: MonitorMessage[];
  files: OutputFile[];
  isRunning: boolean;
  result: string;
  timestamp: string;
}

interface ConversationThreadProps {
  turns: ChatTurn[];
}

const AGENT_CAPABILITIES = [
  {
    tool: "网络搜索",
    title: "公开信息检索",
    desc: "接入 Tavily，抓取最新新闻、政策与行业资料，返回带来源链接的原始证据。",
    icon: <CloudServerOutlined aria-hidden />,
  },
  {
    tool: "结构化查询",
    title: "业务数据统计",
    desc: "自动发现表名与字段，执行 SQL 完成库存、销售、区域维度的聚合分析。",
    icon: <DatabaseOutlined aria-hidden />,
  },
  {
    tool: "知识库",
    title: "内部文档问答",
    desc: "向量检索私有知识库，返回带出处与页码的原文片段，支撑可核对结论。",
    icon: <FileSearchOutlined aria-hidden />,
  },
  {
    tool: "附件读取",
    title: "上传文件解析",
    desc: "解析 PDF、Word、Excel、Markdown 与纯文本，把用户材料纳入研究上下文。",
    icon: <FileTextOutlined aria-hidden />,
  },
  {
    tool: "成果交付",
    title: "报告生成与导出",
    desc: "多来源信息汇总为 Markdown 研究报告，并按需转换为 PDF 落盘交付。",
    icon: <FileMarkdownOutlined aria-hidden />,
  },
];

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function parseTime(value: string): number | null {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function formatDuration(value: number): string {
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const paddedMinutes = String(minutes).padStart(2, "0");
  const paddedSeconds = String(seconds).padStart(2, "0");

  if (hours > 0) {
    return `${hours}:${paddedMinutes}:${paddedSeconds}`;
  }
  return `${paddedMinutes}:${paddedSeconds}`;
}

function getLastEventTime(
  events: MonitorMessage[],
  eventName?: string,
): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!eventName || event.event === eventName) {
      return parseTime(event.timestamp);
    }
  }
  return null;
}

function getThinkingDuration(
  events: MonitorMessage[],
  fallbackStart: string,
  isRunning: boolean,
  now: number,
): string {
  const startedAt =
    (events[0] ? parseTime(events[0].timestamp) : null) ??
    parseTime(fallbackStart) ??
    now;
  const finishedAt =
    getLastEventTime(events, "task_result") ??
    (!isRunning ? getLastEventTime(events) : null) ??
    now;
  return formatDuration(finishedAt - startedAt);
}

function EventIcon({ event }: { event: string }) {
  if (event === "assistant_call") {
    return <BranchesOutlined aria-hidden />;
  }
  if (event === "tool_start") {
    return <ToolOutlined aria-hidden />;
  }
  if (event === "session_created") {
    return <FileSearchOutlined aria-hidden />;
  }
  if (event === "task_result") {
    return <CheckCircleOutlined aria-hidden />;
  }
  if (event === "task_cancelled") {
    return <StopOutlined aria-hidden />;
  }
  if (event === "error") {
    return <CloseCircleOutlined aria-hidden />;
  }
  return <ClockCircleOutlined aria-hidden />;
}

function FileIcon({ name }: { name: string }) {
  if (name.endsWith(".pdf")) {
    return <FilePdfOutlined aria-hidden />;
  }
  if (name.endsWith(".md")) {
    return <FileMarkdownOutlined aria-hidden />;
  }
  return <FileTextOutlined aria-hidden />;
}

function ThinkingTimeline({ events }: { events: MonitorMessage[] }) {
  const timelineRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    const timelineNode = timelineRef.current;
    if (!timelineNode) {
      return;
    }

    window.requestAnimationFrame(() => {
      timelineNode.scrollTop = timelineNode.scrollHeight;
    });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="thinking-empty">
        <ClockCircleOutlined aria-hidden />
        等待后端推送执行事件
      </div>
    );
  }

  return (
    <ol className="thinking-timeline" ref={timelineRef}>
      {events.map((event, index) => (
        <li
          className={`thinking-event thinking-event--${event.event}`}
          key={`${event.timestamp}-${index}`}
        >
          <span className="thinking-event-icon">
            <EventIcon event={event.event} />
          </span>
          <div>
            <div className="thinking-event-meta">
              <span>{event.event}</span>
              <time dateTime={event.timestamp}>
                {formatTime(event.timestamp)}
              </time>
            </div>
            <p>{event.message}</p>
            {event.event === "assistant_call" ||
            event.event === "tool_start" ? (
              <code>{JSON.stringify(event.data)}</code>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ArtifactShelf({ files }: { files: OutputFile[] }) {
  if (files.length === 0) {
    return (
      <div className="artifact-empty">
        <FileSearchOutlined aria-hidden />
        暂无输出文件
      </div>
    );
  }

  return (
    <div className="artifact-shelf">
      {files.map((file) => (
        <div className="artifact-card" key={file.path}>
          <span className="artifact-icon">
            <FileIcon name={file.name} />
          </span>
          <div className="artifact-copy">
            <strong title={file.name}>{file.name}</strong>
            <span>{formatBytes(file.size)}</span>
          </div>
          <Tooltip title="下载">
            <Button
              aria-label={`下载 ${file.name}`}
              className="artifact-download"
              href={getDownloadUrl(file.path)}
              icon={<DownloadOutlined />}
              shape="circle"
            />
          </Tooltip>
        </div>
      ))}
    </div>
  );
}

function ThinkingLoader({ durationLabel }: { durationLabel: string }) {
  return (
    <div
      className="thinking-loader"
      aria-live="polite"
      aria-label="正在生成回复"
    >
      <div className="loader-status">
        <span className="loader-pulse" aria-hidden />
        <strong>正在研搜</strong>
        <span className="loader-duration">已思考 {durationLabel}</span>
        <span className="loader-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
      </div>
      <div className="loader-track" aria-hidden />
      <ul className="loader-steps" aria-hidden>
        <li>理解问题</li>
        <li>调度工具</li>
        <li>汇总答案</li>
      </ul>
    </div>
  );
}

function AssistantMessage({
  events,
  files,
  isRunning,
  result,
  timestamp,
}: Pick<ChatTurn, "events" | "files" | "isRunning" | "result" | "timestamp">) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!isRunning) {
      return;
    }

    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isRunning]);

  const durationLabel = getThinkingDuration(events, timestamp, isRunning, now);
  const isCancelled = events.some((event) => event.event === "task_cancelled");
  const syncLabel = isRunning
    ? `生成中 · 思考 ${durationLabel}`
    : `${isCancelled ? "已取消" : "已同步"} · 用时 ${durationLabel}`;

  return (
    <article className="chat-message chat-message--assistant">
      <div className="message-avatar">AI</div>
      <div className="message-bubble">
        <div className="message-meta">
          <span>DeepSearch Agents</span>
          <time>{syncLabel}</time>
        </div>

        <details
          className="thinking-block"
          open={isRunning || events.length > 0}
        >
          <summary>
            <span>
              <BranchesOutlined aria-hidden />
              深度研搜过程
            </span>
            <strong>{events.length}</strong>
          </summary>
          <ThinkingTimeline events={events} />
        </details>

        {result ? (
          <div className="assistant-answer">
            <MarkdownRenderer content={result} />
          </div>
        ) : (
          <div className="assistant-answer assistant-answer--pending">
            {isRunning ? (
              <ThinkingLoader durationLabel={durationLabel} />
            ) : (
              "任务完成后会在这里显示最终回复。"
            )}
          </div>
        )}

        <details
          className="thinking-block artifact-block"
          open={files.length > 0}
        >
          <summary>
            <span>
              <FileSearchOutlined aria-hidden />
              输出文件
            </span>
            <strong>{files.length}</strong>
          </summary>
          <ArtifactShelf files={files} />
        </details>
      </div>
    </article>
  );
}

export function ConversationThread({ turns }: ConversationThreadProps) {
  if (turns.length === 0) {
    return (
      <div className="conversation-empty">
        <div className="empty-examples">
          <div className="empty-examples-copy">
            <span className="panel-kicker">SYSTEM CAPABILITIES</span>
            <h3>一主三从，五个工具位已就绪</h3>
            <p>
              主智能体负责拆解任务、调度专家助手并汇总结果，执行轨迹与产出文件会实时回传至对话流。
            </p>
          </div>

          <div className="capability-grid" aria-label="系统能力总览">
            {AGENT_CAPABILITIES.map((item) => (
              <article className="capability-card" key={item.tool}>
                <span className="capability-icon">{item.icon}</span>
                <span className="capability-copy">
                  <span>{item.tool}</span>
                  <strong>{item.title}</strong>
                  <small>{item.desc}</small>
                </span>
              </article>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="conversation-thread" aria-label="聊天消息流">
      {turns.map((turn) => (
        <div className="conversation-turn" key={turn.id}>
          <article className="chat-message chat-message--user">
            <div className="message-bubble">
              <div className="message-meta">
                <span>你</span>
                <time dateTime={turn.timestamp}>
                  {formatTime(turn.timestamp)}
                </time>
              </div>
              <p>{turn.content}</p>
            </div>
          </article>
          <AssistantMessage
            events={turn.events}
            files={turn.files}
            isRunning={turn.isRunning}
            result={turn.result}
            timestamp={turn.timestamp}
          />
        </div>
      ))}
    </div>
  );
}
