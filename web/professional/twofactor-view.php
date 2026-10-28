<?php if (!defined('HST_PRO_MFA_VIEW')) { http_response_code(403); exit; } ?>
<?php
require_once __DIR__ . '/layout.php';
pro_layout_open('Segurança A2F', 'twofactor', $identity, [], [], '');
?>
<main class="pro-main"><a href="/professional/">← Voltar à central</a><section class="pro-card">
<span class="pro-eyebrow">Segurança da conta titular</span><h1>Autenticação de Dois Fatores</h1>
<p>Estado da conta: <strong><?= $enabled ? 'Ativada' : 'Desativada' ?></strong>.</p>
<p>Alterações exigem sua senha atual. A ativação só termina após confirmar um código do autenticador. Códigos já usados são recusados; aguarde o próximo.</p>
<?php if ($error !== ''): ?><p role="alert"><?= pro_escape($error) ?></p><?php endif; ?>
<?php if (($result['state'] ?? '') === 'pending'): ?>
<h2>1. Cadastre no autenticador</h2><p>O QR é gerado localmente. Esta preparação expira em 10 minutos e ainda não ativa A2F.</p>
<img class="qr-code" src="<?= pro_escape($result['qr']) ?>" alt="QR para o autenticador"><p>Chave para cadastro manual: <code><?= pro_escape($result['manual_key']) ?></code></p>
<form method="post" action="/professional/twofactor.php"><input type="hidden" name="token" value="<?= pro_escape($_SESSION['token']) ?>"><input type="hidden" name="action" value="enable">
<label class="pro-label">Senha atual<input type="password" name="password" required maxlength="128" autocomplete="current-password" class="form-control"></label>
<label class="pro-label">Código do autenticador<input name="code" required pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code" class="form-control"></label><button class="button pro-button" type="submit">Confirmar e ativar</button></form>
<?php else: ?>
<form method="post" action="/professional/twofactor.php"><input type="hidden" name="token" value="<?= pro_escape($_SESSION['token']) ?>">
<label class="pro-label">Senha atual<input type="password" name="password" required maxlength="128" autocomplete="current-password" class="form-control"></label>
<?php if ($enabled): ?><label class="pro-label">Código atual ou recuperação descartável<input name="code" required maxlength="40" autocomplete="one-time-code" class="form-control"></label><button class="button pro-button" name="action" value="recovery" type="submit">Renovar códigos de recuperação</button> <button class="button button-secondary pro-button pro-button-quiet" name="action" value="disable" type="submit">Desativar A2F</button>
<?php else: ?><button class="button pro-button" name="action" value="prepare" type="submit">Preparar autenticador</button><?php endif; ?></form>
<?php endif; ?>
<?php if (!empty($result['recovery_codes'])): ?><section aria-label="Códigos de recuperação"><h2>Guarde estes códigos agora</h2><p>Exibidos somente nesta resposta. Cada código permite um único uso junto com sua senha no login. Guarde fora da VPS; renovar invalida os anteriores.</p><pre><?= pro_escape(implode("\n", $result['recovery_codes'])) ?></pre></section><?php endif; ?>
<p class="pro-footnote">Contas existentes continuam aceitando seu autenticador. O segredo antigo deixou de servir como recuperação. Para contas sem códigos descartáveis, renove-os aqui usando senha e autenticador; sem acesso ao fator, solicite recuperação ao administrador por um canal verificado.</p>
</section></main>
<?php pro_layout_close(); ?>
