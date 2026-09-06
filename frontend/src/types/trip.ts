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
}

export interface GenerateRequest {
  destination: string
  days: number
  startDate?: string | null
  travelers?: Travelers
  budgetLimit?: number | null
  preferences?: string
}

export interface ReplanRequest {
  trip: Trip
  request: string
}

export type ProgressStage = 'analyze' | 'plan' | 'enrich' | 'validate'

export type StreamEvent =
  | { type: 'progress'; stage: ProgressStage; message: string }
  | { type: 'thinking'; content: string }
  | { type: 'complete'; trip: Trip }
  | { type: 'error'; code: string; message: string }
