export type ActivityType = 'attraction' | 'meal' | 'transport' | 'hotel' | 'shopping'

export interface Location {
  name: string
  address?: string
  longitude?: number | null
  latitude?: number | null
  amapPoiId?: string
  resolved: boolean
}

export interface Activity {
  id?: string
  name: string
  type: ActivityType
  startTime?: string | null
  endTime?: string | null
  cost?: number | null
  notes?: string
  location?: Location | null
}

export interface Day {
  title?: string
  activities: Activity[]
}

export interface Travelers {
  adults: number
  children: number
}

export interface Trip {
  id?: string
  title?: string
  destination: string
  startDate?: string | null
  travelers?: Travelers
  budgetLimit?: number | null
  days: Day[]
  version?: number
  warnings?: string[]
  /** 最近一次生成/重规划的 AI 思考过程，详情页可展开查看 */
  thinking?: string
  /** 生成时的偏好（带娃、不去网红店），对话修改时服务端注入提示词 */
  preferences?: string
  /** 与 AI 的对话历史，随行程持久化 */
  chat?: ChatMessage[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  ts?: string
}

export interface GenerateRequest {
  destination: string
  days: number
  startDate?: string | null
  travelers?: Travelers
  budgetLimit?: number | null
  preferences?: string
  /** AI 思考深度：low=快速（浅思考），high=深度（慢但更合理）；不传跟随服务端默认 */
  thinking_effort?: 'low' | 'high'
  /** 客户端请求标识：生成任务化后作为断线重连的凭据 */
  request_id?: string
}

export interface ReplanRequest {
  trip: Trip
  request: string
  thinking_effort?: 'low' | 'high'
}

export interface ReplayRequest {
  /** 重放接口无需请求体 */
}

export interface ChatRequest {
  trip: Trip
  message: string
  thinking_effort?: 'low' | 'high'
  /** 用户长期偏好档案，服务端注入系统提示词 */
  profile?: string[]
}

export type ProgressStage = 'analyze' | 'plan' | 'enrich' | 'validate'

export type StreamEvent =
  | { type: 'progress'; stage: ProgressStage; message: string }
  | { type: 'thinking'; content: string }
  | { type: 'complete'; trip: Trip }
  | { type: 'error'; code: string; message: string }
