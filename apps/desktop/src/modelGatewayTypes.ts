export interface ModelGatewayProvider {
  provider_id: string;
  local: boolean;
  enabled: boolean;
  operations: string[];
}

export interface ModelGatewayRoute {
  provider?: string;
  model?: string;
  local?: boolean;
  route_id?: string;
  error?: string;
}

export interface ModelGatewayStatus {
  providers: ModelGatewayProvider[];
  routes: Record<string, ModelGatewayRoute>;
}

export interface ModelGatewayResolveRequest {
  capability: string;
  model?: string | null;
  local_only?: boolean;
}

export interface ModelGatewayResolvedRoute {
  capability: string;
  provider: string;
  model: string;
  local: boolean;
  explicit_model: boolean;
  route_id: string;
}
