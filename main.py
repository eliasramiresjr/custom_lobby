import discord
from discord.ext import commands
import random
import asyncio

# Configura o bot com prefixo e intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Classe para gerenciar o estado do lobby
class DraftLobby:
    def __init__(self):
        self.message = None  # Mensagem do lobby
        self.turn_message = None  # Mensagem do turno atual
        self.coin_toss_message = None  # Mensagem de "Cara ou coroa"
        self.captain1 = None
        self.captain2 = None
        self.available_players = []
        self.team1 = []
        self.team2 = []
        self.draft_started = False
        self.current_turn = None  # Capitão que está escolhendo
        self.first_picker = None  # Quem começou o draft

    def is_full(self):
        return self.captain1 is not None and self.captain2 is not None

    def reset_draft(self):
        # Move os jogadores dos times de volta para disponíveis
        self.available_players.extend(self.team1)
        self.available_players.extend(self.team2)
        self.team1 = []
        self.team2 = []
        self.draft_started = False
        self.current_turn = None
        # Mantém o first_picker para que o mesmo capitão comece após o re-draft
        # first_picker não é resetado aqui
        if self.turn_message:
            self.turn_message = None  # Limpa a referência, deleção é feita no chamador
        if self.coin_toss_message:
            self.coin_toss_message = None  # Limpa a referência, deleção é feita no chamador

    def is_draft_complete(self):
        return len(self.team1) >= 4 and len(self.team2) >= 4

# Estado global do lobby
lobby = None

# Função para criar o embed do lobby
def create_lobby_embed(lobby):
    embed = discord.Embed(title="Lobby Custom", color=discord.Color.blue())
    embed.add_field(
        name="Time 1",
        value=f"Capitão: {lobby.captain1.mention if lobby.captain1 else 'Vazio'}\n" +
        "\n".join([f"- {p.mention}" for p in lobby.team1]) or "-",
        inline=True
    )
    embed.add_field(
        name="Time 2",
        value=f"Capitão: {lobby.captain2.mention if lobby.captain2 else 'Vazio'}\n" +
        "\n".join([f"- {p.mention}" for p in lobby.team2]) or "-",
        inline=True
    )
    embed.add_field(
        name="Jogadores Disponíveis",
        value="\n".join([f"- {p.mention}" for p in lobby.available_players]) or "Nenhum",
        inline=False
    )
    return embed

# Classe para gerenciar botões do lobby
class LobbyView(discord.ui.View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby
        # Adiciona os botões "Iniciar" e "Re-draft" ao inicializar a view
        self.add_item(StartDraftButton(self.lobby))
        self.add_item(RedraftButton(self.lobby))

    @discord.ui.button(label="Capitão 1", style=discord.ButtonStyle.primary)
    async def captain1_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if self.lobby.captain1 is None:
            # Remove de outros papéis
            if user == self.lobby.captain2:
                self.lobby.captain2 = None
            if user in self.lobby.available_players:
                self.lobby.available_players.remove(user)
            self.lobby.captain1 = user
        await interaction.response.defer()
        await self.update_lobby(interaction)

    @discord.ui.button(label="Capitão 2", style=discord.ButtonStyle.primary)
    async def captain2_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if self.lobby.captain2 is None:
            # Remove de outros papéis
            if user == self.lobby.captain1:
                self.lobby.captain1 = None
            if user in self.lobby.available_players:
                self.lobby.available_players.remove(user)
            self.lobby.captain2 = user
        await interaction.response.defer()
        await self.update_lobby(interaction)

    @discord.ui.button(label="Jogar", style=discord.ButtonStyle.green)
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        reset_draft = False
        was_waiting = False

        # Verifica se o draft está pausado aguardando jogadores
        if (self.lobby.draft_started and 
            self.lobby.turn_message and 
            self.lobby.available_players == [] and  # Antes de adicionar o novo jogador
            self.lobby.current_turn is not None):
            was_waiting = True

        if user not in self.lobby.available_players:
            # Remove de outros papéis e reseta o draft se for um capitão
            if user == self.lobby.captain1:
                self.lobby.captain1 = None
                reset_draft = True
                self.lobby.available_players.extend(self.lobby.team1)
                self.lobby.available_players.extend(self.lobby.team2)
                self.lobby.team1 = []
                self.lobby.team2 = []
            if user == self.lobby.captain2:
                self.lobby.captain2 = None
                reset_draft = True
                self.lobby.available_players.extend(self.lobby.team1)
                self.lobby.available_players.extend(self.lobby.team2)
                self.lobby.team1 = []
                self.lobby.team2 = []
            self.lobby.available_players.append(user)

        if reset_draft:
            if self.lobby.turn_message:
                await self.lobby.turn_message.delete()
                self.lobby.turn_message = None
            if self.lobby.coin_toss_message:
                await self.lobby.coin_toss_message.delete()
                self.lobby.coin_toss_message = None
            self.lobby.reset_draft()
            was_waiting = False  # Reset do draft invalida a retomada automática

        await interaction.response.defer()
        await self.update_lobby(interaction)

        # Se o draft estava pausado e agora há jogadores disponíveis, retoma automaticamente
        if was_waiting and self.lobby.available_players and self.lobby.current_turn:
            view = PlayerSelectView(self.lobby)
            await self.lobby.turn_message.edit(content=f"{self.lobby.current_turn.mention}, sua vez de escolher!", view=view)

    @discord.ui.button(label="Sair", style=discord.ButtonStyle.red)
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        reset_draft = False
        if user == self.lobby.captain1:
            self.lobby.captain1 = None
            reset_draft = True
            self.lobby.available_players.extend(self.lobby.team1)
            self.lobby.available_players.extend(self.lobby.team2)
            self.lobby.team1 = []
            self.lobby.team2 = []
        elif user == self.lobby.captain2:
            self.lobby.captain2 = None
            reset_draft = True
            self.lobby.available_players.extend(self.lobby.team1)
            self.lobby.available_players.extend(self.lobby.team2)
            self.lobby.team1 = []
            self.lobby.team2 = []
        elif user in self.lobby.available_players:
            self.lobby.available_players.remove(user)
        elif user in self.lobby.team1:
            self.lobby.team1.remove(user)
            self.lobby.available_players.append(user)
            reset_draft = True
        elif user in self.lobby.team2:
            self.lobby.team2.remove(user)
            self.lobby.available_players.append(user)
            reset_draft = True
        if reset_draft:
            if self.lobby.turn_message:
                await self.lobby.turn_message.delete()
                self.lobby.turn_message = None
            if self.lobby.coin_toss_message:
                await self.lobby.coin_toss_message.delete()
                self.lobby.coin_toss_message = None
            self.lobby.reset_draft()
        await interaction.response.defer()
        await self.update_lobby(interaction)

    async def update_lobby(self, interaction):
        embed = create_lobby_embed(self.lobby)
        await interaction.message.edit(embed=embed, view=self)

# Botão para iniciar o draft
class StartDraftButton(discord.ui.Button):
    def __init__(self, lobby):
        super().__init__(label="Iniciar", style=discord.ButtonStyle.green)
        self.lobby = lobby

    async def callback(self, interaction: discord.Interaction):
        if not self.lobby.is_full():
            await interaction.response.send_message("Ambos os capitães precisam estar preenchidos para iniciar o draft!", ephemeral=True)
            return
        if interaction.user not in [self.lobby.captain1, self.lobby.captain2]:
            await interaction.response.defer()
            return
        self.lobby.draft_started = True
        # Só sorteia o first_picker se ainda não foi definido
        if self.lobby.first_picker is None:
            self.lobby.first_picker = random.choice([self.lobby.captain1, self.lobby.captain2])
        self.lobby.current_turn = self.lobby.first_picker
        if self.lobby.coin_toss_message:
            await self.lobby.coin_toss_message.delete()
        await interaction.response.send_message(f"Cara ou coroa: {self.lobby.first_picker.mention} escolhe primeiro!")
        self.lobby.coin_toss_message = await interaction.original_response()
        await self.send_select_menu(interaction)

    async def send_select_menu(self, interaction):
        if self.lobby.is_draft_complete():
            last_captain = self.lobby.current_turn
            view = SideSelectionView(self.lobby)
            if self.lobby.turn_message:
                await self.lobby.turn_message.delete()
                self.lobby.turn_message = None
            await interaction.channel.send(f"{last_captain.mention}, escolha o lado!", view=view)
            return
        if not self.lobby.available_players:
            if self.lobby.turn_message:
                await self.lobby.turn_message.edit(content="Aguardando jogadores disponíveis...")
            else:
                self.lobby.turn_message = await interaction.channel.send("Aguardando jogadores disponíveis...")
            return
        view = PlayerSelectView(self.lobby)
        if self.lobby.turn_message:
            await self.lobby.turn_message.edit(content=f"{self.lobby.current_turn.mention}, sua vez de escolher!", view=view)
        else:
            self.lobby.turn_message = await interaction.channel.send(f"{self.lobby.current_turn.mention}, sua vez de escolher!", view=view)

# Botão para re-draft
class RedraftButton(discord.ui.Button):
    def __init__(self, lobby):
        super().__init__(label="Re-draft", style=discord.ButtonStyle.red)
        self.lobby = lobby

    async def callback(self, interaction: discord.Interaction):
        if not self.lobby.is_full():
            await interaction.response.send_message("Ambos os capitães precisam estar preenchidos para reiniciar o draft!", ephemeral=True)
            return
        if interaction.user not in [self.lobby.captain1, self.lobby.captain2]:
            await interaction.response.defer()
            return
        if self.lobby.turn_message:
            await self.lobby.turn_message.delete()
            self.lobby.turn_message = None
        if self.lobby.coin_toss_message:
            await self.lobby.coin_toss_message.delete()
            self.lobby.coin_toss_message = None
        self.lobby.reset_draft()
        # Atualiza o embed do lobby para refletir o estado após o reset
        await self.lobby.message.edit(embed=create_lobby_embed(self.lobby), view=LobbyView(self.lobby))
        # Inicia o draft automaticamente
        self.lobby.draft_started = True
        # Mantém o first_picker (já preservado no reset_draft) e define o current_turn
        if self.lobby.first_picker is None:  # Caso o first_picker não tenha sido definido (improvável aqui)
            self.lobby.first_picker = random.choice([self.lobby.captain1, self.lobby.captain2])
        self.lobby.current_turn = self.lobby.first_picker
        await interaction.response.send_message("Draft reiniciado! Continuando com o mesmo capitão inicial.")
        # Inicia o draft chamando a lógica de send_select_menu
        if self.lobby.is_draft_complete():
            last_captain = self.lobby.current_turn
            view = SideSelectionView(self.lobby)
            await interaction.channel.send(f"{last_captain.mention}, escolha o lado!", view=view)
            return
        if not self.lobby.available_players:
            self.lobby.turn_message = await interaction.channel.send("Aguardando jogadores disponíveis...")
            return
        view = PlayerSelectView(self.lobby)
        self.lobby.turn_message = await interaction.channel.send(f"{self.lobby.current_turn.mention}, sua vez de escolher!", view=view)

# Menu para escolher jogadores
class PlayerSelectView(discord.ui.View):
    def __init__(self, lobby):
        super().__init__(timeout=60)
        self.lobby = lobby
        options = [discord.SelectOption(label=p.display_name, value=str(p.id)) for p in self.lobby.available_players]
        select = discord.ui.Select(placeholder="Escolha um jogador", options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        if interaction.user != self.lobby.current_turn:
            await interaction.response.defer()
            return
        selected_id = int(interaction.data['values'][0])
        selected_player = discord.utils.get(self.lobby.available_players, id=selected_id)
        self.lobby.available_players.remove(selected_player)
        if self.lobby.current_turn == self.lobby.captain1:
            self.lobby.team1.append(selected_player)
        else:
            self.lobby.team2.append(selected_player)
        self.lobby.current_turn = self.lobby.captain2 if self.lobby.current_turn == self.lobby.captain1 else self.lobby.captain1
        await interaction.message.edit(view=None)
        await self.lobby.message.edit(embed=create_lobby_embed(self.lobby), view=LobbyView(self.lobby))
        if not self.lobby.is_draft_complete():
            if self.lobby.available_players:
                await self.lobby.turn_message.edit(content=f"{self.lobby.current_turn.mention}, sua vez de escolher!", view=PlayerSelectView(self.lobby))
            else:
                await self.lobby.turn_message.edit(content="Aguardando jogadores disponíveis...")

# Botões para escolher lado
class SideSelectionView(discord.ui.View):
    def __init__(self, lobby):
        super().__init__(timeout=None)
        self.lobby = lobby

    @discord.ui.button(label="Azul", style=discord.ButtonStyle.primary)
    async def blue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.lobby.current_turn:
            await interaction.response.defer()
            return
        await interaction.response.send_message(f"{interaction.user.mention} escolheu o lado **Azul**!")
        await interaction.message.edit(view=None)
        self.lobby.message = None  # Encerra o lobby

    @discord.ui.button(label="Vermelho", style=discord.ButtonStyle.red)
    async def red_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.lobby.current_turn:
            await interaction.response.defer()
            return
        await interaction.response.send_message(f"{interaction.user.mention} escolheu o lado **Vermelho**!")
        await interaction.message.edit(view=None)
        self.lobby.message = None  # Encerra o lobby

# Comando !start
@bot.command()
async def start(ctx):
    global lobby
    if lobby and lobby.message:
        await ctx.send("Já existe um lobby ativo! Use !clear para limpar o lobby atual.")
        return
    lobby = DraftLobby()
    embed = create_lobby_embed(lobby)
    view = LobbyView(lobby)
    lobby.message = await ctx.send(embed=embed, view=view)

# Comando !clear
@bot.command()
async def clear(ctx):
    global lobby
    if lobby and lobby.message:
        if lobby.turn_message:
            await lobby.turn_message.delete()
        if lobby.coin_toss_message:
            await lobby.coin_toss_message.delete()
        await lobby.message.delete()
        lobby = None
        await ctx.send("Lobby limpo com sucesso!")
    else:
        await ctx.send("Não há nenhum lobby ativo!")

# Evento de inicialização
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

# Substitua pelo seu token
bot.run("MTM2Njk4ODgyMDc5MjM0NDU5Nw.GXsnvE.HD3133IzE59kTVaCSGD_urMF0qyqHS-LrjtKL8")
