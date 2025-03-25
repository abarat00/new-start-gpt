import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

def hidden_init(layer):
    fan_in = layer.weight.data.size()[1]
    lim = 1.0 / np.sqrt(fan_in)
    return (-lim, lim)

class PortfolioCritic(nn.Module):
    def __init__(self, state_size, action_size, seed=0, fcs1_units=256, fc2_units=128, fc3_units=64, use_batch_norm=True):
        super(PortfolioCritic, self).__init__()
        self.seed = torch.manual_seed(seed)
        self.use_batch_norm = use_batch_norm
        
        self.fcs1 = nn.Linear(state_size + action_size, fcs1_units)
        self.fc2 = nn.Linear(fcs1_units, fc2_units)
        self.fc3 = nn.Linear(fc2_units, fc3_units)
        self.fc4 = nn.Linear(fc3_units, 1)
        
        if use_batch_norm:
            self.bn1 = nn.BatchNorm1d(fcs1_units)
            self.bn2 = nn.BatchNorm1d(fc2_units)
            self.bn3 = nn.BatchNorm1d(fc3_units)
        
        self.reset_parameters()
    
    def reset_parameters(self):
        self.fcs1.weight.data.uniform_(*hidden_init(self.fcs1))
        self.fcs1.bias.data.fill_(0)
        self.fc2.weight.data.uniform_(*hidden_init(self.fc2))
        self.fc2.bias.data.fill_(0)
        self.fc3.weight.data.uniform_(*hidden_init(self.fc3))
        self.fc3.bias.data.fill_(0)
        self.fc4.weight.data.uniform_(-3e-4, 3e-4)
        self.fc4.bias.data.fill_(0)
    
    def forward(self, state, action):
        x = torch.cat((state, action), dim=1)
        if self.use_batch_norm:
            x = F.relu(self.bn1(self.fcs1(x)))
            x = F.relu(self.bn2(self.fc2(x)))
            x = F.relu(self.bn3(self.fc3(x)))
        else:
            x = F.relu(self.fcs1(x))
            x = F.relu(self.fc2(x))
            x = F.relu(self.fc3(x))
        return self.fc4(x)

class AssetEncoder(nn.Module):
    def __init__(self, features_per_asset, encoding_size=16, seed=0, output_size=None):
        super(AssetEncoder, self).__init__()
        self.seed = torch.manual_seed(seed)
        self.features_per_asset = features_per_asset
        self.encoding_size = encoding_size
        self.output_size = output_size or encoding_size
        
        self.fc1 = nn.Linear(features_per_asset, 32)
        self.fc2 = nn.Linear(32, self.output_size)
        self.first_forward_done = False
        self.reset_parameters()
    
    def reset_parameters(self):
        self.fc1.weight.data.uniform_(*hidden_init(self.fc1))
        self.fc1.bias.data.fill_(0)
        self.fc2.weight.data.uniform_(*hidden_init(self.fc2))
        self.fc2.bias.data.fill_(0)
    
    def forward(self, state, num_assets):
        batch_size = state.size(0)
        total_features = state.size(1)
        asset_features_total = num_assets * self.features_per_asset
        
        if not self.first_forward_done:
            # Sostituisco i print di debug con un eventuale logging, se necessario
            # E.g., logging.debug(f"AssetEncoder - Primo forward: state shape {state.shape}")
            self.first_forward_done = True
        
        if total_features < asset_features_total:
            padding_needed = asset_features_total - total_features
            padding = torch.zeros(batch_size, padding_needed, device=state.device)
            state = torch.cat([state, padding], dim=1)
            total_features = state.size(1)
        
        asset_features = state[:, :asset_features_total]
        extra_features = state[:, asset_features_total:] if total_features > asset_features_total else None
        
        try:
            asset_features = asset_features.view(batch_size, num_assets, self.features_per_asset)
        except RuntimeError as e:
            # Se si verifica un errore, gestiamo il fallback
            total_elements = asset_features.numel()
            safe_features_per_asset = total_elements // (batch_size * num_assets)
            self.features_per_asset = safe_features_per_asset
            asset_features = asset_features[:, :batch_size * num_assets * safe_features_per_asset]
            asset_features = asset_features.view(batch_size, num_assets, safe_features_per_asset)
        
        x = F.relu(self.fc1(asset_features))
        asset_encodings = F.relu(self.fc2(x))
        asset_encodings = asset_encodings.view(batch_size, num_assets * self.output_size)
        if extra_features is not None:
            return torch.cat((asset_encodings, extra_features), dim=1)
        return asset_encodings

class EnhancedPortfolioActor(nn.Module):
    def __init__(self, state_size, action_size, features_per_asset, seed=0, 
                 fc1_units=256, fc2_units=128, encoding_size=32, use_attention=True,
                 attention_size=None, encoder_output_size=None):
        super(EnhancedPortfolioActor, self).__init__()
        self.seed = torch.manual_seed(seed)
        self.action_size = action_size
        self.features_per_asset = features_per_asset
        self.use_attention = use_attention
        
        self.asset_encoder = AssetEncoder(features_per_asset, encoding_size=encoding_size, seed=seed,
                                          output_size=encoder_output_size)
        
        self.extra_features = state_size - (features_per_asset * action_size)
        self.attention = None
        self.value = None
        self.fc1 = None
        self.fc2 = None
        self.fc3 = None
        
        self.ln1 = None
        self.ln2 = None
        
        self.fc1_units = fc1_units
        self.fc2_units = fc2_units
        
        self.layers_initialized = False
        self.effective_encoding_size = None
        self.fc_input_size = None
    
    def initialize_layers(self, encoded_size):
        # Inizializza i layer FC dinamicamente
        self.fc1 = nn.Linear(encoded_size, self.fc1_units)
        self.ln1 = nn.LayerNorm(self.fc1_units)
        self.fc2 = nn.Linear(self.fc1_units, self.fc2_units)
        self.ln2 = nn.LayerNorm(self.fc2_units)
        self.fc3 = nn.Linear(self.fc2_units, self.action_size)
        self.reset_parameters()
        self.layers_initialized = True
    
    def reset_parameters(self):
        if self.fc1 is not None:
            self.fc1.weight.data.uniform_(*hidden_init(self.fc1))
            self.fc1.bias.data.fill_(0)
        if self.fc2 is not None:
            self.fc2.weight.data.uniform_(*hidden_init(self.fc2))
            self.fc2.bias.data.fill_(0)
        if self.fc3 is not None:
            self.fc3.weight.data.uniform_(-3e-4, 3e-4)
            self.fc3.bias.data.fill_(0)
    
    def initialize_attention_layers(self, effective_encoding_size):
        self.attention = nn.Linear(effective_encoding_size, 1)
        self.value = nn.Linear(effective_encoding_size, effective_encoding_size)
        fan_in = effective_encoding_size
        lim = 1.0 / np.sqrt(fan_in)
        self.attention.weight.data.uniform_(-lim, lim)
        self.attention.bias.data.fill_(0)
        self.value.weight.data.uniform_(-lim, lim)
        self.value.bias.data.fill_(0)
        self.effective_encoding_size = effective_encoding_size
    
    def apply_attention(self, encoded_assets, batch_size):
        total_size = encoded_assets.size(1)
        extra_features = None
        if self.extra_features > 0 and total_size > self.action_size * self.features_per_asset:
            extra_features = encoded_assets[:, -self.extra_features:]
            encoded_assets = encoded_assets[:, :-self.extra_features]
            total_size = encoded_assets.size(1)
        
        if total_size % self.action_size == 0:
            effective_encoding_size = total_size // self.action_size
        else:
            effective_encoding_size = (total_size + self.action_size - 1) // self.action_size
            padding_needed = effective_encoding_size * self.action_size - total_size
            if padding_needed > 0:
                padding = torch.zeros(batch_size, padding_needed, device=encoded_assets.device)
                encoded_assets = torch.cat([encoded_assets, padding], dim=1)
                total_size = encoded_assets.size(1)
        
        if self.attention is None or self.value is None or self.effective_encoding_size != effective_encoding_size:
            self.initialize_attention_layers(effective_encoding_size)
        
        try:
            assets = encoded_assets.view(batch_size, self.action_size, effective_encoding_size)
        except RuntimeError as e:
            total_elements = encoded_assets.numel()
            safe_encoding_size = total_elements // (batch_size * self.action_size)
            self.initialize_attention_layers(safe_encoding_size)
            assets = encoded_assets.view(batch_size, self.action_size, safe_encoding_size)
            effective_encoding_size = safe_encoding_size
        
        attention_scores = self.attention(assets).squeeze(-1)
        attention_weights = F.softmax(attention_scores, dim=1).unsqueeze(-1)
        values = self.value(assets)
        context = (attention_weights * values).sum(dim=1)
        context_expanded = context.unsqueeze(1).expand(-1, self.action_size, -1)
        enhanced_assets = torch.cat((assets, context_expanded), dim=2)
        enhanced_size = enhanced_assets.size(2) * self.action_size
        flattened = enhanced_assets.view(batch_size, enhanced_size)
        if extra_features is not None:
            flattened = torch.cat((flattened, extra_features), dim=1)
        return flattened
    
    def forward(self, state):
        batch_size = state.size(0)
        encoded_state = self.asset_encoder(state, self.action_size)
        if self.use_attention:
            encoded_state = self.apply_attention(encoded_state, batch_size)
        if not self.layers_initialized or self.fc1.weight.shape[1] != encoded_state.size(1):
            self.initialize_layers(encoded_state.size(1))
        x = F.relu(self.ln1(self.fc1(encoded_state)))
        x = F.relu(self.ln2(self.fc2(x)))
        return self.fc3(x)