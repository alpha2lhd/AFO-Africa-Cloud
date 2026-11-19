-- =====================================================================
-- AfricaCloud - Plateforme de Signalement d'Incidents Techniques
-- African Skills Olympics 2026 - Database Schema
-- =====================================================================

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'Moyenne',
    reporter TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Ouvert',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Données initiales d'exemple (Incidents Techniques AfricaCloud)
INSERT INTO issues (title, category, priority, reporter, description, status) VALUES
('Latence sur le noeud VM2 (App1)', 'Serveur / VM', 'Haute', 'Amine (Support NOC)', 'Temps de réponse élevé constaté sur 69.41.31.11 lors du pic de trafic.', 'En cours'),
('Vérification routage inter-VLAN 22 vers VLAN 33', 'Réseau / VLAN', 'Critique', 'Sarah (Admin Réseau)', 'Perte intermittente de paquets entre VM3 (69.41.31.12) et la BDD VM4 (31.69.41.20).', 'Ouvert'),
('Validation sauvegarde nocturne 04h00 RedSync', 'Sauvegarde (VM5)', 'Basse', 'Karim (Supervision)', 'Confirmation du dump SQL de VM4 vers VM5 (41.69.31.50).', 'Résolu');
